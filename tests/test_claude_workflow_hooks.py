"""Behavior tests for .claude/hooks/workflow_rules.py (the session workflow hooks)."""

import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

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


def test_sonnet_subagents_are_allowed():
    assert run_hook("subagent", agent_call(subagent_type="pstack-worker")) is None
    assert run_hook("subagent", agent_call(subagent_type="architect")) is None
    assert run_hook("subagent", agent_call(subagent_type="Explore", model="sonnet")) is None
    assert (
        run_hook("subagent", agent_call(subagent_type="general-purpose", model="claude-sonnet-5-5"))
        is None
    )


def test_opus_advisor_is_allowed():
    assert run_hook("subagent", agent_call(subagent_type="opus-advisor")) is None


def test_non_sonnet_subagents_are_denied():
    assert denied(run_hook("subagent", agent_call(subagent_type="Explore")))
    assert denied(run_hook("subagent", agent_call(subagent_type="general-purpose")))
    assert denied(run_hook("subagent", agent_call()))
    assert denied(run_hook("subagent", agent_call(subagent_type="fork", model="sonnet")))
    assert denied(run_hook("subagent", agent_call(subagent_type="pstack-worker", model="haiku")))


def test_other_tools_pass_through():
    assert run_hook("subagent", {"tool_name": "Bash", "tool_input": {"command": "ls"}}) is None


def write_transcript(tmp_path, entries):
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return str(path)


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


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


def test_stop_turn_starts_at_relayed_meta_message(tmp_path):
    """Cloud sessions store relayed messages with isMeta; they still start a turn."""
    relayed = {**user("<relay>do the next thing</relay>"), "isMeta": True}
    path = write_transcript(
        tmp_path,
        [
            user("first"),
            assistant(tool_use("Agent", subagent_type="opus-advisor", prompt="check")),
            tool_result(),
            relayed,
            assistant(tool_use("Bash", command="ls")),
            tool_result(),
        ],
    )
    assert run_hook("stop", {"transcript_path": path})["decision"] == "block"


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


def test_stop_rechecks_work_done_after_a_fix_first(tmp_path):
    """Work on the advisor's FIX FIRST is reviewed again, even on Claude Code's second Stop."""
    session = uuid.uuid4().hex
    turn = [user("go"), assistant(tool_use("Bash", command="ls")), tool_result()]
    assert stop(write_transcript(tmp_path, turn), session=session)["decision"] == "block"
    turn += [advisor(), tool_result(), assistant(tool_use("Edit", file_path="a.py")), tool_result()]
    out = stop(write_transcript(tmp_path, turn), active=True, session=session)
    assert out["decision"] == "block"
    turn += [advisor(), tool_result()]
    assert stop(write_transcript(tmp_path, turn), active=True, session=session) is None


def test_stop_blocks_at_most_three_times_per_turn(tmp_path):
    session = uuid.uuid4().hex
    turn = [user("go")]
    outs = []
    for _ in range(4):
        turn += [assistant(tool_use("Bash", command="ls")), tool_result()]
        outs.append(stop(write_transcript(tmp_path, turn), active=bool(outs), session=session))
        turn += [advisor(), tool_result()]
    assert [o and o["decision"] for o in outs] == ["block", "block", "block", None]


def test_stop_cap_resets_on_a_new_turn(tmp_path):
    session = uuid.uuid4().hex
    turn = [user("first")]
    for _ in range(3):
        turn += [assistant(tool_use("Bash", command="ls")), tool_result()]
        stop(write_transcript(tmp_path, turn), session=session)
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
    (tmp / "claude-workflow-hooks").write_text("a file where the counter dir should be")
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
