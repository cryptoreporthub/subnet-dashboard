#!/usr/bin/env python3
"""Claude Code hooks that enforce this repo's session workflow.

One script, three modes, picked by the first argument:

  prompt    UserPromptSubmit: restate the workflow rules every turn.
  subagent  PreToolUse on Agent/Task: deny a subagent that would not run on
            Sonnet (the Opus advisor is the one exception).
  stop      Stop: block the end of a turn whose last tool work came after
            the last advisor call. Re-checks after each block (so work done on
            the advisor's FIX FIRST is reviewed too), up to MAX_STOP_BLOCKS
            blocks per turn.

Active only in Claude Code cloud sessions (CLAUDE_CODE_REMOTE=true) and never
under GitHub Actions (GITHUB_ACTIONS=true), so the Claude review and mention
workflows in this repo run without these rules.
Stdlib only. Any error in this script allows the action, so a broken hook
never wedges a session.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile

ADVISOR_AGENT = "opus-advisor"
WORKER_AGENT = "pstack-worker"
# Agent files in .claude/agents that already pin model: sonnet.
SONNET_AGENTS = {WORKER_AGENT, "architect", "pr-review"}
AGENT_TOOLS = {"Agent", "Task"}
# Bookkeeping tools that change nothing, so they don't count as work.
NON_WORK_TOOLS = {"TodoWrite", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "ToolSearch", "Skill"}

# Blocks per turn: the first plus two re-checks. The cap stops an endless
# advisor loop; past it the turn may end without another review.
MAX_STOP_BLOCKS = 3

RULES = (
    "Workflow rules for this repo (hooks enforce them):\n"
    "1. Poteto mode is on: follow ~/.claude/skills/poteto-mode/SKILL.md and the "
    "pstack skills in ~/.claude/skills.\n"
    f"2. Use Sonnet pstack subagents for ALL tasks: delegate work to the "
    f"`{WORKER_AGENT}` agent (or another agent with model sonnet). Other "
    "subagents are denied.\n"
    f"3. Before you end a turn that did work, consult the Opus advisor: the "
    f"`{ADVISOR_AGENT}` agent, or the built-in `advisor` tool if it is on."
)


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload))


def on_prompt(_event: dict) -> None:
    _emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": RULES,
            }
        }
    )


def subagent_verdict(tool_input: dict) -> str | None:
    """Return a deny reason, or None when the subagent call is allowed."""
    agent = (tool_input.get("subagent_type") or "").strip()
    model = (tool_input.get("model") or "").strip().lower()
    if agent == ADVISOR_AGENT:
        return None
    if agent in SONNET_AGENTS and model in ("", "sonnet"):
        return None
    if agent != "fork" and (model == "sonnet" or model.startswith("claude-sonnet")):
        return None
    shown = agent or "the default agent"
    return (
        f"Denied: {shown} would not run on Sonnet. This repo uses Sonnet pstack "
        f"subagents for ALL tasks. Retry with subagent_type `{WORKER_AGENT}`, or "
        "pass model: sonnet. Only the advisor may run on Opus, as "
        f"`{ADVISOR_AGENT}`."
    )


def on_subagent(event: dict) -> None:
    if event.get("tool_name") not in AGENT_TOOLS:
        return
    reason = subagent_verdict(event.get("tool_input") or {})
    if reason is None:
        return
    _emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    )


def _blocks(entry: dict) -> list:
    content = (entry.get("message") or {}).get("content")
    return content if isinstance(content, list) else []


# Fields Claude Code sets on user entries that a tool produced (tool results,
# a loaded skill's text) rather than a new message that starts a turn.
TOOL_DERIVED_KEYS = ("toolUseResult", "sourceToolUseID", "sourceToolAssistantUUID")


def _starts_turn(entry: dict) -> bool:
    """A user entry that opens a turn: a typed prompt or a relayed message.

    Cloud sessions store relayed messages with isMeta set, so isMeta does not
    rule an entry out.
    """
    if entry.get("type") != "user" or entry.get("turnCompanion"):
        return False
    if any(entry.get(key) is not None for key in TOOL_DERIVED_KEYS):
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return True
    return not any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content or []
    )


def turn_start(entries: list[dict]) -> int:
    """Index of the entry that started the current turn, or -1."""
    for i in range(len(entries) - 1, -1, -1):
        if _starts_turn(entries[i]):
            return i
    return -1


def current_turn(entries: list[dict]) -> list[dict]:
    """Entries after the message that started the current turn."""
    return entries[turn_start(entries) + 1 :]


def _messages(turn: list[dict]) -> list[list[dict]]:
    """The turn's assistant content blocks, grouped by API message.

    Claude Code writes one entry per content block, so parallel tool calls
    from one message share a message id across several entries.
    """
    groups: dict = {}
    for n, entry in enumerate(turn):
        if entry.get("type") != "assistant":
            continue
        key = (entry.get("message") or {}).get("id") or ("entry", n)
        groups.setdefault(key, []).extend(
            b for b in _blocks(entry) if isinstance(b, dict)
        )
    return list(groups.values())


def _is_advisor(block: dict) -> bool:
    if block.get("type") == "advisor_tool_result" or block.get("name") == "advisor":
        return True
    return (
        block.get("type") == "tool_use"
        and block.get("name") in AGENT_TOOLS
        and (block.get("input") or {}).get("subagent_type") == ADVISOR_AGENT
    )


def _is_work(block: dict) -> bool:
    return (
        block.get("type") == "tool_use"
        and not _is_advisor(block)
        and block.get("name") not in NON_WORK_TOOLS
    )


def turn_summary(turn: list[dict]) -> tuple[bool, bool]:
    """(did tool work, consulted the advisor after the last work) for one turn.

    Work clears an earlier advisor call. An advisor call in the same message
    as work does not count, since the two run side by side and the advisor
    cannot see that work's result.
    """
    worked = consulted = False
    for blocks in _messages(turn):
        if any(_is_work(b) for b in blocks):
            worked, consulted = True, False
        elif any(_is_advisor(b) for b in blocks):
            consulted = True
    return worked, consulted


def _read_transcript(path: str) -> list[dict]:
    entries = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _state_path(event: dict) -> str:
    session = str(event.get("session_id") or event.get("transcript_path"))
    name = hashlib.sha256(session.encode()).hexdigest()[:32] + ".json"
    return os.path.join(tempfile.gettempdir(), "claude-workflow-hooks", name)


def _blocks_so_far(event: dict, turn_key: str) -> int | None:
    """Stop blocks already made this turn, or None if the state can't be read."""
    try:
        with open(_state_path(event), encoding="utf-8") as fh:
            state = json.load(fh)
    except FileNotFoundError:
        return 0
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict) or state.get("turn") != turn_key:
        return 0
    count = state.get("blocks")
    return count if isinstance(count, int) else 0


def _record_block(event: dict, turn_key: str, count: int) -> bool:
    path = _state_path(event)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump({"turn": turn_key, "blocks": count}, fh)
        os.replace(path + ".tmp", path)
        return True
    except OSError:
        return False


def on_stop(event: dict) -> None:
    path = event.get("transcript_path")
    if not path:
        return
    entries = _read_transcript(path)
    start = turn_start(entries)
    worked, consulted = turn_summary(entries[start + 1 :])
    if not worked or consulted:
        return
    first = entries[start] if start >= 0 else {}
    turn_key = f"{start}:{first.get('uuid', '')}"
    count = _blocks_so_far(event, turn_key)
    if count is not None and count >= MAX_STOP_BLOCKS:
        return
    # Without a working counter, fall back to Claude Code's own one-shot guard
    # so a broken state file can never loop the session.
    if count is None or not _record_block(event, turn_key, count + 1):
        if event.get("stop_hook_active"):
            return
    _emit(
        {
            "decision": "block",
            "reason": (
                "Before you finish, consult the Opus advisor on this turn's "
                f"work since its last check: start the `{ADVISOR_AGENT}` agent "
                "with the task, what you did and your evidence (or call the "
                "built-in `advisor` tool if it is on). Then act on what it says "
                "and end the turn. If you change anything after it answers, "
                "it checks again."
            ),
        }
    )


MODES = {"prompt": on_prompt, "subagent": on_subagent, "stop": on_stop}


def main() -> int:
    if os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        return 0
    if os.environ.get("GITHUB_ACTIONS") == "true":  # Actions always sets this
        return 0
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    handler = MODES.get(mode)
    if handler is None:
        return 0
    try:
        raw = sys.stdin.read()
        handler(json.loads(raw) if raw.strip() else {})
    except Exception as exc:  # never wedge a session on a hook bug
        sys.stderr.write(f"workflow_rules {mode}: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
