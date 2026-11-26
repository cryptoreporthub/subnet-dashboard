"""Behavior tests for .claude/hooks/workflow_rules.py (the session workflow hooks)."""

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "workflow_rules.py"
BASE = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_REMOTE", "GITHUB_ACTIONS")}
CLOUD = {**BASE, "CLAUDE_CODE_REMOTE": "true"}
NOT_CLOUD = BASE
STATE_DIR = tempfile.mkdtemp(prefix="workflow-hooks-test-")


def run_hook(mode, event, env=CLOUD):
    env = {**env, "TMPDIR": STATE_DIR}  # keep the Stop counter out of the real tmp
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), mode],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def agent_call(**tool_input):
    return {"tool_name": "Agent", "tool_input": {"prompt": "x", **tool_input}}


def denied(out):
    return bool(out) and out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_prompt_mode_restates_rules():
    out = run_hook("prompt", {"prompt": "hi"})
    context = out["hookSpecificOutput"]["additionalContext"]
    assert "poteto-mode" in context
    assert "pstack-worker" in context
    assert "opus-advisor" in context


def _gemini_items():
    spec = importlib.util.spec_from_file_location("workflow_rules", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.GEMINI_ITEMS


def test_prompt_mode_says_when_to_bring_in_gemini():
    """Every prompt carries the Gemini step with the shared item list and its hand-over phrase."""
    context = run_hook("prompt", {"prompt": "hi"})["hookSpecificOutput"]["additionalContext"]
    assert _gemini_items() in context
    assert "Time for Gemini" in context


@pytest.mark.parametrize("agent", ["opus-advisor", "pstack-worker"])
def test_agents_quote_the_same_gemini_items(agent):
    """The advisor and the worker carry the hook's own list, so the three copies can't drift."""
    text = (SCRIPT.parent.parent / "agents" / f"{agent}.md").read_text()
    assert _gemini_items() in text


def test_worker_goes_ahead_once_gemini_is_settled():
    """The worker can't see the Gemini status, so the brief settles it and approved work goes on."""
    text = (SCRIPT.parent.parent / "agents" / "pstack-worker.md").read_text()
    assert "that the brief doesn't settle, don't decide it" in text
    assert "Gemini reviewed it or the user skipped it, go ahead" in text


def test_sonnet_subagents_are_allowed():
    assert run_hook("subagent", agent_call(subagent_type="pstack-worker")) is None
    assert run_hook("subagent", agent_call(subagent_type="architect")) is None
    assert run_hook("subagent", agent_call(subagent_type="Explore", model="sonnet")) is None
    assert (
        run_hook("subagent", agent_call(subagent_type="general-purpose", model="claude-sonnet-5-5"))
        is None
    )


@pytest.mark.parametrize("model", ["haiku", "sonnet", "claude-sonnet-5-5", "inherit", "opusplan", "best"])
def test_advisor_on_another_model_is_denied(model):
    assert denied(run_hook("subagent", agent_call(subagent_type="opus-advisor", model=model)))


@pytest.mark.parametrize("model", ["opus", "opus[1m]", "claude-opus-5-5"])
def test_advisor_on_opus_is_allowed(model):
    assert not denied(run_hook("subagent", agent_call(subagent_type="opus-advisor", model=model)))


@pytest.mark.parametrize("model", ["sonnet[1m]", "claude-sonnet-5-5[1m]"])
def test_sonnet_1m_variant_is_allowed(model):
    assert run_hook("subagent", agent_call(subagent_type="pstack-worker", model=model)) is None
    assert run_hook("subagent", agent_call(subagent_type="Explore", model=model)) is None


@pytest.mark.parametrize(
    "tool_input",
    [
        {"subagent_type": "opus-advisor"},
        {"subagent_type": "pstack-worker"},
        {"subagent_type": "Explore", "model": "sonnet"},
        {"subagent_type": "general-purpose", "model": "claude-sonnet-5-5"},
    ],
)
@pytest.mark.parametrize("background", [False, True])
def test_only_foreground_subagents_may_launch(tool_input, background):
    call = agent_call(**tool_input, **({"run_in_background": True} if background else {}))
    assert denied(run_hook("subagent", call)) == background


@pytest.mark.parametrize("odd", [5, ["opus-advisor"], {}, "whole input"])
def test_non_text_agent_name_is_no_review(tmp_path, odd):
    # A malformed call must leave the turn blocked, not crash the gate open.
    call = tool_use("Agent", subagent_type=odd, prompt="check")
    if odd == "whole input":
        call["input"] = "opus-advisor"
    path = write_transcript(
        tmp_path,
        [user("fix it"), assistant(tool_use("Bash", command="ls")), tool_result(),
         assistant(call), tool_result()],
    )
    out = run_hook("stop", {"transcript_path": path, "stop_hook_active": False})
    assert out["decision"] == "block"


@pytest.mark.parametrize("odd", [5, ["sonnet"], {}])
def test_non_text_fields_are_denied_not_crashed(odd):
    assert denied(run_hook("subagent", agent_call(subagent_type=odd)))
    assert denied(run_hook("subagent", agent_call(subagent_type="Explore", model=odd)))
    assert denied(run_hook("subagent", agent_call(subagent_type="pstack-worker", model=odd)))
    assert denied(run_hook("subagent", agent_call(subagent_type="opus-advisor", model=odd)))
    assert denied(run_hook("subagent", {"tool_name": "Agent", "tool_input": odd}))


@pytest.mark.parametrize("odd", [5, ["opus"], {}])
def test_advisor_with_non_text_model_is_no_review(tmp_path, odd):
    call = tool_use("Agent", subagent_type="opus-advisor", model=odd, prompt="check")
    path = write_transcript(
        tmp_path,
        [user("fix it"), assistant(tool_use("Bash", command="ls")), tool_result(),
         assistant(call), tool_result()],
    )
    out = run_hook("stop", {"transcript_path": path, "stop_hook_active": False})
    assert out["decision"] == "block"


def test_null_model_reads_as_omitted(tmp_path):
    # null is how JSON tools often send an unset optional field. It runs on
    # the agent file's model (opus for the advisor), so it is allowed and
    # counts as the review, exactly like an omitted model.
    assert run_hook("subagent", agent_call(subagent_type="opus-advisor", model=None)) is None
    assert run_hook("subagent", agent_call(subagent_type="pstack-worker", model=None)) is None
    assert denied(run_hook("subagent", agent_call(subagent_type="Explore", model=None)))
    call = tool_use("Agent", subagent_type="opus-advisor", model=None, prompt="check")
    path = write_transcript(
        tmp_path,
        [user("fix it"), assistant(tool_use("Bash", command="ls")), tool_result(),
         assistant(call), tool_result()],
    )
    assert run_hook("stop", {"transcript_path": path, "stop_hook_active": False}) is None


@pytest.mark.parametrize("kind", [["human"], {"k": "human"}])
def test_odd_origin_kind_cannot_end_the_turn_unchecked(tmp_path, kind):
    typed = {**user("fix it"), "origin": {"kind": kind}}
    path = write_transcript(
        tmp_path, [user("start"), typed, assistant(tool_use("Bash", command="ls")), tool_result()]
    )
    out = run_hook("stop", {"transcript_path": path, "stop_hook_active": False})
    assert out["decision"] == "block"


def test_odd_message_id_does_not_block_a_read_only_turn(tmp_path):
    read = {"type": "assistant", "message": {"id": ["odd"], "content": [tool_use("Read", file_path="x")]}}
    path = write_transcript(tmp_path, [user("what's in x?"), read, tool_result()])
    assert run_hook("stop", {"transcript_path": path, "stop_hook_active": False}) is None


@pytest.mark.parametrize(
    "bad_line",
    [b"\xff\xfe{\"type\": \"user\"}", b"[" * 100_000 + b"]" * 100_000],
    ids=["invalid-utf8", "deeply-nested"],
)
def test_unparseable_line_after_work_still_blocks(tmp_path, bad_line):
    # A line cut mid-character or nested too deep is skipped like any non-JSON
    # line; the work before it still needs the advisor.
    path = write_transcript(
        tmp_path, [user("fix it"), assistant(tool_use("Bash", command="ls")), tool_result()]
    )
    with open(path, "ab") as fh:
        fh.write(bad_line + b"\n")
    out = run_hook("stop", {"transcript_path": path, "stop_hook_active": False})
    assert out["decision"] == "block"


def test_unreadable_turn_blocks_instead_of_ending_unchecked(tmp_path):
    # A list as an errored result's tool_use_id can't go in the failed set; the
    # summary raises, and the gate must treat that as work without a review.
    odd = {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": ["x"], "is_error": True, "content": "no"}]}}
    path = write_transcript(
        tmp_path,
        [user("fix it"), assistant(tool_use("Agent", subagent_type="opus-advisor", prompt="c")),
         odd],
    )
    out = run_hook("stop", {"transcript_path": path, "stop_hook_active": False})
    assert out["decision"] == "block"


@pytest.mark.parametrize("odd", [["not", "an", "entry"], 7, "text"])
def test_odd_transcript_lines_still_block(tmp_path, odd):
    # Odd lines are skipped and an odd message reads as empty: the turn's
    # work still needs the advisor, so the gate can't crash open.
    odd_message = {"type": "assistant", "message": odd}
    path = write_transcript(
        tmp_path,
        [user("fix it"), odd, assistant(tool_use("Bash", command="ls")), odd_message,
         tool_result()],
    )
    out = run_hook("stop", {"transcript_path": path, "stop_hook_active": False})
    assert out["decision"] == "block"


def test_padded_advisor_name_counts_as_the_review(tmp_path):
    call = tool_use("Agent", subagent_type=" opus-advisor ", prompt="check")
    path = write_transcript(
        tmp_path,
        [user("fix it"), assistant(tool_use("Bash", command="ls")), tool_result(),
         assistant(call), tool_result()],
    )
    assert run_hook("stop", {"transcript_path": path, "stop_hook_active": False}) is None


def test_background_advisor_call_does_not_count(tmp_path):
    call = tool_use("Agent", subagent_type="opus-advisor", run_in_background=True, prompt="check")
    path = write_transcript(
        tmp_path,
        [user("fix it"), assistant(tool_use("Bash", command="ls")), tool_result(),
         assistant(call), tool_result()],
    )
    out = run_hook("stop", {"transcript_path": path, "stop_hook_active": False})
    assert out["decision"] == "block"


def test_opus_advisor_is_allowed():
    assert run_hook("subagent", agent_call(subagent_type="opus-advisor")) is None


def test_non_sonnet_subagents_are_denied():
    assert denied(run_hook("subagent", agent_call(subagent_type="Explore")))
    assert denied(run_hook("subagent", agent_call(subagent_type="general-purpose")))
    assert denied(run_hook("subagent", agent_call()))
    assert denied(run_hook("subagent", agent_call(subagent_type="fork", model="sonnet")))
    assert denied(run_hook("subagent", agent_call(subagent_type="pstack-worker", model="haiku")))


def test_fork_deny_does_not_suggest_a_model_override():
    # The Agent tool ignores a model override for a fork, so the hint must not offer one.
    out = run_hook("subagent", agent_call(subagent_type="fork", model="sonnet"))
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "pstack-worker" in reason and "model: sonnet" not in reason


def test_other_tools_pass_through():
    assert run_hook("subagent", {"tool_name": "Bash", "tool_input": {"command": "ls"}}) is None


def write_transcript(tmp_path, entries):
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return str(path)


def user(text):
    return {"type": "user", "uuid": uuid.uuid4().hex, "message": {"role": "user", "content": text}}


def tool_result():
    return {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}}


def assistant(*blocks):
    return {"type": "assistant", "message": {"content": list(blocks)}}


def tool_use(name, **tool_input):
    return {"type": "tool_use", "name": name, "input": tool_input}


def test_stop_blocks_work_without_advisor(tmp_path):
    path = write_transcript(
        tmp_path, [user("fix it"), assistant(tool_use("Bash", command="ls")), tool_result()]
    )
    out = run_hook("stop", {"transcript_path": path, "stop_hook_active": False})
    assert out["decision"] == "block"


def test_stop_allows_after_advisor_agent(tmp_path):
    path = write_transcript(
        tmp_path,
        [
            user("fix it"),
            assistant(tool_use("Bash", command="ls")),
            tool_result(),
            assistant(tool_use("Agent", subagent_type="opus-advisor", prompt="check")),
            tool_result(),
        ],
    )
    assert run_hook("stop", {"transcript_path": path}) is None


def test_stop_blocks_when_the_advisor_call_errored(tmp_path):
    call = tool_use("Agent", subagent_type="opus-advisor", prompt="check")
    call["id"] = "toolu_advisor"
    failed = {"type": "tool_result", "tool_use_id": "toolu_advisor", "is_error": True,
              "content": "agent failed"}
    path = write_transcript(
        tmp_path,
        [
            user("fix it"),
            assistant(tool_use("Bash", command="ls")),
            tool_result(),
            assistant(call),
            {"type": "user", "message": {"content": [failed]}},
        ],
    )
    out = run_hook("stop", {"transcript_path": path, "stop_hook_active": False})
    assert out["decision"] == "block"


def test_non_opus_advisor_call_does_not_count(tmp_path):
    # Even if the denied call's result were written without is_error.
    call = tool_use("Agent", subagent_type="opus-advisor", model="haiku", prompt="check")
    path = write_transcript(
        tmp_path,
        [
            user("fix it"),
            assistant(tool_use("Bash", command="ls")),
            tool_result(),
            assistant(call),
            tool_result(),
        ],
    )
    out = run_hook("stop", {"transcript_path": path, "stop_hook_active": False})
    assert out["decision"] == "block"


def test_stop_allows_advisor_after_another_tool_failed(tmp_path):
    bash = tool_use("Bash", command="false")
    bash["id"] = "toolu_bash"
    call = tool_use("Agent", subagent_type="opus-advisor", prompt="check")
    call["id"] = "toolu_advisor"
    bash_failed = {"type": "tool_result", "tool_use_id": "toolu_bash", "is_error": True,
                   "content": "Exit code 1"}
    advisor_ok = {"type": "tool_result", "tool_use_id": "toolu_advisor", "content": "READY"}
    path = write_transcript(
        tmp_path,
        [
            user("fix it"),
            assistant(bash),
            {"type": "user", "message": {"content": [bash_failed]}},
            assistant(call),
            {"type": "user", "message": {"content": [advisor_ok]}},
        ],
    )
    assert run_hook("stop", {"transcript_path": path}) is None


# Every result shape Claude Code's own classifier names for the built-in
# advisor, with the verdict the gate must reach after work.
BUILTIN_ADVISOR_RESULTS = [
    ({"type": "advisor_result", "text": "Looks fine.", "stop_reason": "end_turn"}, "allow"),
    ({"type": "advisor_redacted_result", "stop_reason": "end_turn"}, "allow"),
    ({"type": "advisor_tool_result_error", "error_code": "overloaded"}, "block"),
    ({"type": "advisor_result", "stop_reason": "refusal"}, "block"),
    ({"type": "advisor_result", "text": "I can't help.", "stop_reason": "refusal"}, "block"),
    ({"type": "advisor_redacted_result", "stop_reason": "refusal"}, "block"),
]


@pytest.mark.parametrize(("content", "verdict"), BUILTIN_ADVISOR_RESULTS)
def test_stop_gate_on_each_builtin_advisor_result(tmp_path, content, verdict):
    call = {"type": "server_tool_use", "id": "srvtoolu_1", "name": "advisor", "input": {}}
    result = {"type": "advisor_tool_result", "tool_use_id": "srvtoolu_1", "content": content}
    path = write_transcript(
        tmp_path,
        [
            user("fix it"),
            assistant(tool_use("Edit", file_path="a.py")),
            tool_result(),
            assistant(call, result),
        ],
    )
    out = run_hook("stop", {"transcript_path": path, "stop_hook_active": False})
    assert (out or {}).get("decision", "allow") == verdict


def test_compaction_summary_does_not_hide_earlier_work(tmp_path):
    summary = {"type": "user", "isCompactSummary": True, "isVisibleInTranscriptOnly": True,
               "uuid": uuid.uuid4().hex,
               "message": {"content": "This session is being continued from an earlier one"}}
    path = write_transcript(
        tmp_path,
        [
            user("fix it"),
            assistant(tool_use("Edit", file_path="a.py")),
            tool_result(),
            summary,
            assistant({"type": "text", "text": "done"}),
        ],
    )
    out = run_hook("stop", {"transcript_path": path, "stop_hook_active": False})
    assert out["decision"] == "block"


def test_subagent_prompt_does_not_hide_earlier_work(tmp_path):
    worker_prompt = {**user("read a.py and report"), "isSidechain": True}
    path = write_transcript(
        tmp_path,
        [
            user("fix it"),
            assistant(tool_use("Edit", file_path="a.py")),
            tool_result(),
            assistant(tool_use("Agent", subagent_type="pstack-worker", prompt="read a.py")),
            worker_prompt,
            {**assistant(tool_use("Read", file_path="a.py")), "isSidechain": True},
            assistant({"type": "text", "text": "done"}),
        ],
    )
    out = run_hook("stop", {"transcript_path": path, "stop_hook_active": False})
    assert out["decision"] == "block"


def test_advisor_has_no_bash_or_write_tools():
    # The advisor reads untrusted text (the diff, the worker's summary, PR text),
    # so it gets read-only tools only: nothing it reads can make it run anything.
    agent = (SCRIPT.parents[1] / "agents" / "opus-advisor.md").read_text(encoding="utf-8")
    tools_line = next(l for l in agent.splitlines() if l.startswith("tools:"))
    tools = {t.strip() for t in tools_line.split(":", 1)[1].split(",")}
    assert tools == {"Read", "Grep", "Glob"}


def test_background_notification_does_not_hide_earlier_work(tmp_path):
    notice = {**user("<task-notification>worker finished</task-notification>"),
              "origin": {"kind": "task-notification"}}
    path = write_transcript(
        tmp_path,
        [
            user("fix it"),
            assistant(tool_use("Edit", file_path="a.py")),
            tool_result(),
            notice,
            assistant({"type": "text", "text": "done"}),
        ],
    )
    out = run_hook("stop", {"transcript_path": path, "stop_hook_active": False})
    assert out["decision"] == "block"


def test_message_typed_by_a_person_starts_a_new_turn(tmp_path):
    typed = {**user("thanks, what's next?"), "origin": {"kind": "human"}}
    path = write_transcript(
        tmp_path,
        [
            user("fix it"),
            assistant(tool_use("Edit", file_path="a.py")),
            tool_result(),
            typed,
            assistant({"type": "text", "text": "the roadmap"}),
        ],
    )
    out = run_hook("stop", {"transcript_path": path, "stop_hook_active": False})
    assert (out or {}).get("decision", "allow") == "allow"


def test_subagents_own_steps_do_not_undo_the_advisor_call(tmp_path):
    path = write_transcript(
        tmp_path,
        [
            user("fix it"),
            assistant(tool_use("Edit", file_path="a.py")),
            tool_result(),
            assistant(tool_use("Agent", subagent_type="opus-advisor", prompt="check")),
            {**assistant(tool_use("Bash", command="pytest")), "isSidechain": True},
            tool_result(),
            assistant({"type": "text", "text": "done"}),
        ],
    )
    out = run_hook("stop", {"transcript_path": path, "stop_hook_active": False})
    assert (out or {}).get("decision", "allow") == "allow"


def test_stop_allows_after_advisor_tool(tmp_path):
    path = write_transcript(
        tmp_path,
        [
            user("fix it"),
            assistant(tool_use("Edit", file_path="a.py")),
            tool_result(),
            assistant({"type": "server_tool_use", "name": "advisor", "input": {}}),
        ],
    )
    assert run_hook("stop", {"transcript_path": path}) is None


def test_stop_blocks_work_done_after_the_advisor(tmp_path):
    path = write_transcript(
        tmp_path,
        [
            user("fix it"),
            assistant(tool_use("Agent", subagent_type="opus-advisor", prompt="check")),
            tool_result(),
            assistant(tool_use("Bash", command="rm -rf build")),
            tool_result(),
        ],
    )
    assert run_hook("stop", {"transcript_path": path})["decision"] == "block"


def test_stop_allows_bookkeeping_after_the_advisor(tmp_path):
    path = write_transcript(
        tmp_path,
        [
            user("fix it"),
            assistant(tool_use("Edit", file_path="a.py")),
            tool_result(),
            assistant(tool_use("Agent", subagent_type="opus-advisor", prompt="check")),
            tool_result(),
            assistant(tool_use("TodoWrite", todos=[])),
            tool_result(),
        ],
    )
    assert run_hook("stop", {"transcript_path": path}) is None


def test_stop_ignores_turns_without_tool_work(tmp_path):
    path = write_transcript(tmp_path, [user("thanks"), assistant({"type": "text", "text": "np"})])
    assert run_hook("stop", {"transcript_path": path}) is None


def test_stop_only_counts_the_current_turn(tmp_path):
    path = write_transcript(
        tmp_path,
        [
            user("first"),
            assistant(tool_use("Agent", subagent_type="opus-advisor", prompt="check")),
            tool_result(),
            user("second"),
            assistant(tool_use("Bash", command="ls")),
            tool_result(),
        ],
    )
    assert run_hook("stop", {"transcript_path": path})["decision"] == "block"


def test_stop_relayed_meta_message_does_not_hide_earlier_work(tmp_path):
    """A system-written (isMeta) entry never starts a turn, so work before it still counts."""
    relayed = {**user("<relay>do the next thing</relay>"), "isMeta": True}
    path = write_transcript(
        tmp_path,
        [
            user("first"),
            assistant(tool_use("Edit", file_path="a.py")),
            tool_result(),
            relayed,
            assistant({"type": "text", "text": "done"}),
        ],
    )
    assert run_hook("stop", {"transcript_path": path})["decision"] == "block"


def test_stop_mid_turn_reminder_does_not_hide_work(tmp_path):
    reminder = {**user("<system-reminder>note</system-reminder>"), "isMeta": True}
    path = write_transcript(
        tmp_path,
        [user("fix it"), assistant(tool_use("Edit", file_path="a.py")), tool_result(), reminder,
         assistant({"type": "text", "text": "done"})],
    )
    assert run_hook("stop", {"transcript_path": path})["decision"] == "block"


def test_stop_read_only_turn_needs_no_advisor(tmp_path):
    path = write_transcript(
        tmp_path,
        [user("what does main.py do?"), assistant(tool_use("Read", file_path="main.py")),
         tool_result(), assistant(tool_use("Grep", pattern="def ")), tool_result(),
         assistant({"type": "text", "text": "It starts the app."})],
    )
    assert run_hook("stop", {"transcript_path": path}) is None


def test_stop_turn_that_only_asks_needs_no_advisor(tmp_path):
    path = write_transcript(
        tmp_path,
        [user("set it up"), assistant(tool_use("AskUserQuestion", questions=[])), tool_result()],
    )
    assert run_hook("stop", {"transcript_path": path}) is None


def test_stop_loaded_skill_text_does_not_split_the_turn(tmp_path):
    skill_text = {**user("skill body"), "isMeta": True, "sourceToolUseID": "toolu_1"}
    path = write_transcript(
        tmp_path,
        [
            user("go"),
            assistant(tool_use("Agent", subagent_type="opus-advisor", prompt="check")),
            tool_result(),
            assistant(tool_use("Skill", skill="tdd")),
            skill_text,
            assistant({"type": "text", "text": "done"}),
        ],
    )
    assert run_hook("stop", {"transcript_path": path}) is None


def stop(path, active=False, session=None):
    event = {"transcript_path": path, "stop_hook_active": active}
    event["session_id"] = session or uuid.uuid4().hex
    return run_hook("stop", event)


def advisor():
    return assistant(tool_use("Agent", subagent_type="opus-advisor", prompt="check"))


def block_feedback(reason, shape):
    """The Stop hook's block reason as Claude Code writes it back to the transcript."""
    if shape == "attachment":
        return {
            "type": "attachment",
            "attachment": {
                "type": "hook_blocking_error",
                "hookName": "Stop",
                "blockingError": {"blockingError": reason, "command": "workflow_rules.py stop"},
            },
        }
    if shape == "user-unprefixed":
        return user(reason)
    entry = user(f"Stop hook feedback:\n{reason}")
    return {**entry, "isMeta": True} if shape == "user" else entry


# The gate must not depend on how Claude Code writes the reason back, so every
# shape, including one that reads exactly like a typed prompt, is covered.
SHAPES = pytest.mark.parametrize("shape", ["attachment", "user", "user-plain", "user-unprefixed"])


@SHAPES
def test_stop_rechecks_work_done_after_a_fix_first(tmp_path, shape):
    """Work on the advisor's FIX FIRST is reviewed again, even on Claude Code's second Stop."""
    session = uuid.uuid4().hex
    turn = [user("go"), assistant(tool_use("Bash", command="ls")), tool_result()]
    out = stop(write_transcript(tmp_path, turn), session=session)
    assert out["decision"] == "block"
    turn += [block_feedback(out["reason"], shape), advisor(), tool_result()]
    turn += [assistant(tool_use("Edit", file_path="a.py")), tool_result()]
    out = stop(write_transcript(tmp_path, turn), active=True, session=session)
    assert out["decision"] == "block"
    turn += [block_feedback(out["reason"], shape), advisor(), tool_result()]
    assert stop(write_transcript(tmp_path, turn), active=True, session=session) is None


@SHAPES
def test_stop_ignoring_the_block_does_not_end_the_turn(tmp_path, shape):
    """Answering the block with no advisor call is still blocked: the reason doesn't start a turn."""
    session = uuid.uuid4().hex
    turn = [user("go"), assistant(tool_use("Bash", command="ls")), tool_result()]
    out = stop(write_transcript(tmp_path, turn), session=session)
    turn += [block_feedback(out["reason"], shape), assistant({"type": "text", "text": "done"})]
    assert stop(write_transcript(tmp_path, turn), active=True, session=session)["decision"] == "block"


@SHAPES
def test_stop_blocks_at_most_three_times_per_turn(tmp_path, shape):
    session = uuid.uuid4().hex
    turn = [user("go")]
    outs = []
    for _ in range(4):
        turn += [assistant(tool_use("Bash", command="ls")), tool_result()]
        out = stop(write_transcript(tmp_path, turn), active=bool(outs), session=session)
        outs.append(out)
        if out:
            turn.append(block_feedback(out["reason"], shape))
        turn += [advisor(), tool_result()]
    assert [o and o["decision"] for o in outs] == ["block", "block", "block", None]


def test_prompt_opening_like_block_reason_is_an_ordinary_prompt(tmp_path):
    """A typed prompt that happens to open like the block reason starts a turn like any other."""
    path = write_transcript(
        tmp_path,
        [
            user("first"),
            assistant(tool_use("Bash", command="ls")),
            tool_result(),
            user("Stop hook feedback: what does this mean?"),
            assistant({"type": "text", "text": "It means..."}),
        ],
    )
    assert stop(path) is None


def test_stop_rewritten_transcript_falls_back_to_the_whole_transcript(tmp_path):
    """If the stored turn start is gone (as after compaction), the re-check widens, never narrows."""
    session = uuid.uuid4().hex
    turn = [user("earlier"), assistant({"type": "text", "text": "hi"}), user("go")]
    turn += [assistant(tool_use("Edit", file_path="a.py")), tool_result()]
    out = stop(write_transcript(tmp_path, turn), session=session)
    assert out["decision"] == "block"
    rewritten = [user("summary of earlier work"), assistant(tool_use("Edit", file_path="a.py"))]
    rewritten += [tool_result(), block_feedback(out["reason"], "user-unprefixed")]
    rewritten += [assistant({"type": "text", "text": "done"})]
    out = stop(write_transcript(tmp_path, rewritten), active=True, session=session)
    assert out["decision"] == "block"


def test_stop_cap_resets_on_a_new_turn(tmp_path):
    session = uuid.uuid4().hex
    turn = [user("first")]
    for n in range(3):
        turn += [assistant(tool_use("Bash", command="ls")), tool_result()]
        stop(write_transcript(tmp_path, turn), active=n > 0, session=session)
    turn += [user("second"), assistant(tool_use("Bash", command="ls")), tool_result()]
    assert stop(write_transcript(tmp_path, turn), session=session)["decision"] == "block"


def test_stop_advisor_beside_work_in_one_message_does_not_count(tmp_path):
    path = write_transcript(
        tmp_path,
        [
            user("go"),
            assistant(
                tool_use("Bash", command="make"),
                tool_use("Agent", subagent_type="opus-advisor", prompt="check"),
            ),
            tool_result(),
            tool_result(),
        ],
    )
    assert stop(path)["decision"] == "block"


def test_stop_reads_one_message_split_across_entries(tmp_path):
    """Claude Code writes each parallel tool call of one message as its own entry."""
    msg = {"id": "msg_1"}
    work = {"type": "assistant", "message": {**msg, "content": [tool_use("Bash", command="make")]}}
    adv = {
        "type": "assistant",
        "message": {
            **msg,
            "content": [tool_use("Agent", subagent_type="opus-advisor", prompt="check")],
        },
    }
    path = write_transcript(tmp_path, [user("go"), work, adv, tool_result(), tool_result()])
    assert stop(path)["decision"] == "block"


def test_stop_without_counter_falls_back_to_one_block(tmp_path):
    """If the counter can't be stored, Claude Code's own one-shot guard still prevents a loop."""
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    (tmp / f"claude-workflow-hooks-{os.getuid()}").write_text("a file where the counter dir should be")
    path = write_transcript(tmp_path, [user("go"), assistant(tool_use("Bash", command="ls"))])
    env = {**CLOUD, "TMPDIR": str(tmp)}
    for active, expect in ((False, "block"), (True, None)):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "stop"],
            input=json.dumps({"transcript_path": path, "stop_hook_active": active, "session_id": "s"}),
            capture_output=True,
            text=True,
            env=env,
        )
        out = json.loads(proc.stdout) if proc.stdout.strip() else None
        assert (out and out["decision"]) == expect


def test_stop_refuses_a_shared_or_linked_state_dir(tmp_path):
    """Another user's or a world-writable counter dir is not trusted: fall back to one block."""
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    target = tmp_path / "elsewhere"
    target.mkdir()
    (tmp / f"claude-workflow-hooks-{os.getuid()}").symlink_to(target)
    path = write_transcript(tmp_path, [user("go"), assistant(tool_use("Bash", command="ls"))])
    env = {**CLOUD, "TMPDIR": str(tmp)}
    for active, expect in ((False, "block"), (True, None)):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "stop"],
            input=json.dumps({"transcript_path": path, "stop_hook_active": active, "session_id": "s"}),
            capture_output=True,
            text=True,
            env=env,
        )
        out = json.loads(proc.stdout) if proc.stdout.strip() else None
        assert (out and out["decision"]) == expect
    assert list(target.iterdir()) == []  # nothing written through the link


def test_hooks_do_nothing_outside_cloud_sessions(tmp_path):
    """The GitHub Actions review jobs run Claude Code in this repo; they must be untouched."""
    path = write_transcript(tmp_path, [user("go"), assistant(tool_use("Bash", command="ls"))])
    assert run_hook("prompt", {"prompt": "hi"}, env=NOT_CLOUD) is None
    assert run_hook("subagent", agent_call(subagent_type="Explore"), env=NOT_CLOUD) is None
    assert run_hook("stop", {"transcript_path": path}, env=NOT_CLOUD) is None
    in_actions = {**CLOUD, "GITHUB_ACTIONS": "true"}
    assert run_hook("prompt", {"prompt": "hi"}, env=in_actions) is None
    assert run_hook("stop", {"transcript_path": path}, env=in_actions) is None


def test_bad_input_allows():
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "stop"],
        input="not json",
        capture_output=True,
        text=True,
        env=CLOUD,
    )
    assert proc.returncode == 0
    assert proc.stdout == ""


def test_agents_trusted_as_sonnet_pin_sonnet():
    """Every agent the guard lets through without a model must pin Sonnet in its file."""
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import workflow_rules
    finally:
        sys.path.pop(0)
    agents_dir = SCRIPT.parent.parent / "agents"
    for name in workflow_rules.SONNET_AGENTS:
        text = (agents_dir / f"{name}.md").read_text()
        front = text.split("---")[1]
        assert "\nmodel: sonnet\n" in front, f"{name}.md does not pin model: sonnet"
    advisor = (agents_dir / f"{workflow_rules.ADVISOR_AGENT}.md").read_text().split("---")[1]
    assert "\nmodel: opus\n" in advisor


def test_workflow_tool_is_denied_and_matched():
    # A Workflow script starts its own agents, which this gate never sees, so
    # it would get round the Sonnet-only rule. It is denied, and the settings
    # route it to the gate.
    assert denied(run_hook("subagent", {"tool_name": "Workflow", "tool_input": {"script": "x"}}))
    assert run_hook("subagent", {"tool_name": "Bash", "tool_input": {"command": "ls"}}) is None
    settings_path = Path(__file__).resolve().parent.parent / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text())
    matchers = [m["matcher"] for m in settings["hooks"]["PreToolUse"]]
    assert any(re.fullmatch(m, "Workflow") for m in matchers)
    assert any(re.fullmatch(m, "Agent") for m in matchers)
