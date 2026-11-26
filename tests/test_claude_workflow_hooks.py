"""Behavior tests for .claude/hooks/workflow_rules.py (the session workflow hooks)."""

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "workflow_rules.py"
CLOUD = {**os.environ, "CLAUDE_CODE_REMOTE": "true"}
NOT_CLOUD = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_REMOTE"}


def run_hook(mode, event, env=CLOUD):
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


def test_stop_never_blocks_twice(tmp_path):
    path = write_transcript(tmp_path, [user("go"), assistant(tool_use("Bash", command="ls"))])
    assert run_hook("stop", {"transcript_path": path, "stop_hook_active": True}) is None


def test_hooks_do_nothing_outside_cloud_sessions(tmp_path):
    """The GitHub Actions review jobs run Claude Code in this repo; they must be untouched."""
    path = write_transcript(tmp_path, [user("go"), assistant(tool_use("Bash", command="ls"))])
    assert run_hook("prompt", {"prompt": "hi"}, env=NOT_CLOUD) is None
    assert run_hook("subagent", agent_call(subagent_type="Explore"), env=NOT_CLOUD) is None
    assert run_hook("stop", {"transcript_path": path}, env=NOT_CLOUD) is None


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
