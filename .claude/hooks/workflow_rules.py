#!/usr/bin/env python3
"""Claude Code hooks that enforce this repo's session workflow.

One script, three modes, picked by the first argument:

  prompt    UserPromptSubmit: restate the workflow rules every turn.
  subagent  PreToolUse on Agent/Task: deny a subagent that would not run on
            Sonnet (the Opus advisor is the one exception).
  stop      Stop: block the end of a turn that did tool work but never
            consulted the advisor. Blocks at most once per turn.

Stdlib only. Any error in this script allows the action, so a broken hook
never wedges a session.
"""

from __future__ import annotations

import json
import sys

ADVISOR_AGENT = "opus-advisor"
WORKER_AGENT = "pstack-worker"
# Agent files in .claude/agents that already pin model: sonnet.
SONNET_AGENTS = {WORKER_AGENT, "architect", "pr-review"}
AGENT_TOOLS = {"Agent", "Task"}

RULES = (
    "Workflow rules for this repo (hooks enforce them):\n"
    "1. Poteto mode is on: follow ~/.claude/skills/poteto-mode/SKILL.md and the "
    "pstack skills in ~/.claude/skills.\n"
    f"2. Use Sonnet pstack subagents for ALL tasks: delegate work to the "
    f"`{WORKER_AGENT}` agent (or another agent with model sonnet). Other "
    "subagents are denied.\n"
    f"3. Before you end a turn that did work, consult the advisor: the "
    f"`advisor` tool if you have it, otherwise the `{ADVISOR_AGENT}` agent."
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
    if agent != "fork" and model == "sonnet":
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


def _is_human_prompt(entry: dict) -> bool:
    if entry.get("type") != "user" or entry.get("isMeta"):
        return False
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return True
    return not any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content or []
    )


def current_turn(entries: list[dict]) -> list[dict]:
    """Entries after the last prompt the person typed."""
    for i in range(len(entries) - 1, -1, -1):
        if _is_human_prompt(entries[i]):
            return entries[i + 1 :]
    return entries


def turn_summary(turn: list[dict]) -> tuple[bool, bool]:
    """(did tool work, consulted the advisor) for one turn."""
    worked = consulted = False
    for entry in turn:
        if entry.get("type") != "assistant":
            continue
        for block in _blocks(entry):
            if not isinstance(block, dict):
                continue
            kind, name = block.get("type"), block.get("name")
            if kind == "advisor_tool_result" or name == "advisor":
                consulted = True
            elif kind == "tool_use":
                worked = True
                agent = (block.get("input") or {}).get("subagent_type")
                if name in AGENT_TOOLS and agent == ADVISOR_AGENT:
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


def on_stop(event: dict) -> None:
    if event.get("stop_hook_active"):
        return
    path = event.get("transcript_path")
    if not path:
        return
    worked, consulted = turn_summary(current_turn(_read_transcript(path)))
    if worked and not consulted:
        _emit(
            {
                "decision": "block",
                "reason": (
                    "Before you finish, consult the advisor on this turn's work: "
                    f"call the `advisor` tool, or the `{ADVISOR_AGENT}` agent if "
                    "you don't have it. Then act on what it says and end the turn."
                ),
            }
        )


MODES = {"prompt": on_prompt, "subagent": on_subagent, "stop": on_stop}


def main() -> int:
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
