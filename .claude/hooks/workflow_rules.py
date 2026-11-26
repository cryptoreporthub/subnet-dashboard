#!/usr/bin/env python3
"""Claude Code hooks that enforce this repo's session workflow.

One script, three modes, picked by the first argument:

  prompt    UserPromptSubmit: restate the workflow rules every turn.
  subagent  PreToolUse on Agent/Task: deny a subagent that would not run on
            Sonnet (the Opus advisor is the one exception).
  bash      PreToolUse on Bash: inside the Opus advisor, allow only read-only
            git commands, since the advisor reads untrusted text (the
            worker's summary, the diff, PR text).
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
import shlex
import stat
import sys
import tempfile

ADVISOR_AGENT = "opus-advisor"
WORKER_AGENT = "pstack-worker"
# Agent files in .claude/agents that already pin model: sonnet.
SONNET_AGENTS = {WORKER_AGENT, "architect", "pr-review"}
AGENT_TOOLS = {"Agent", "Task"}
# Tools that change nothing, so they don't count as work: bookkeeping, and
# read-only lookups, so a turn that only reads and answers needs no advisor.
# Bash always counts, since a command can change anything.
NON_WORK_TOOLS = {
    "TodoWrite", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "ToolSearch", "Skill",
    "Read", "Grep", "Glob", "LS", "WebFetch", "WebSearch", "NotebookRead",
}
# ponytail: names are matched exactly, so read-only MCP tools (for example
# mcp__github__pull_request_read) still count as work and ask for the advisor.
# That only over-blocks; guessing from verbs like "get" could let a write through.

# Blocks per Stop chain (one turn): the first plus two re-checks. The cap stops an endless
# advisor loop; past it the turn may end without another review.
MAX_STOP_BLOCKS = 3

STOP_REASON = (
    "Before you finish, consult the Opus advisor on this turn's work since its "
    f"last check: start the `{ADVISOR_AGENT}` agent with the task, what you did "
    "and your evidence (or call the built-in `advisor` tool if it is on). Then "
    "act on what it says and end the turn. If you change anything after it "
    "answers, it checks again."
)

# The one list of Gemini items. The opus-advisor and pstack-worker agent files
# quote it word for word, and a test keeps the three copies the same.
GEMINI_ITEMS = (
    "design decisions, important bug-fix designs, "
    "anything touching auth, public write endpoints, money or data integrity, "
    "and adversarial testing of a finished feature"
)

RULES = (
    "Workflow rules for this repo (hooks back up rules 2 and 3 when they run; "
    "follow all four yourself):\n"
    "1. Poteto mode is on: follow ~/.claude/skills/poteto-mode/SKILL.md and the "
    "pstack skills in ~/.claude/skills.\n"
    f"2. Use Sonnet pstack subagents for ALL tasks: delegate work to the "
    f"`{WORKER_AGENT}` agent (or another agent with model sonnet). Other "
    "subagents are denied.\n"
    f"3. Before you end a turn that did work, consult the Opus advisor: the "
    f"`{ADVISOR_AGENT}` agent, or the built-in `advisor` tool if it is on.\n"
    "4. Gemini step (the user relays to Gemini; you can't reach it). Gemini items "
    f"(medium-to-high impact only) are {GEMINI_ITEMS}. Never for routine work "
    "(small fixes, routine review, CI or config tweaks). On one, tell the user "
    "\"Time for Gemini\": one line on why and a ready-to-paste Gemini prompt (the "
    "context, the exact question or thing to attack, what a good answer looks "
    "like). Don't code the item or hand it to a worker until they reply. For "
    "adversarial testing, ask before the PR is marked ready instead. Don't raise "
    "an item again once the user skipped it or Gemini reviewed it. Give the "
    "advisor each item's Gemini status; it only sees turns with tool work, so a "
    "design-only answer is yours to check."
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
        # The call's model overrides the agent file, so a review on another
        # model would pass the Stop gate as the Opus one.
        if model in ("", "opus", "opus[1m]") or model.startswith("claude-opus"):
            return None
        return (
            f"Denied: `{ADVISOR_AGENT}` must run on Opus. Leave model unset "
            "(the agent file pins opus) or pass model: opus."
        )
    if agent in SONNET_AGENTS and model in ("", "sonnet"):
        return None
    if agent != "fork" and (model == "sonnet" or model.startswith("claude-sonnet")):
        return None
    if agent == "fork":
        # A fork always runs on the parent's model and ignores a model override.
        return (
            "Denied: a fork runs on the main session's model, not Sonnet. This "
            "repo uses Sonnet pstack subagents for ALL tasks. Retry with "
            f"subagent_type `{WORKER_AGENT}`."
        )
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


# What the advisor's Bash may run: read-only git, nothing that runs repo code.
# Everything else is denied, so an instruction injected into the text it
# reviews can't push, post, merge or write files. Test runs go to the worker
# (the advisor asks under Fix first): a test file is code the diff can add,
# and injected text could pick which one to run.
# The gate keys on the `agent_type` that Claude Code puts on hook events from
# inside a subagent, next to `agent_id` (all but its remote-served path). A
# subagent's Bash with `agent_id` but no `agent_type` can't be told apart, so
# it is denied too. The main session's events carry neither and pass. If the
# hook itself errors it fails open, like every hook here.
ADVISOR_GIT = {"diff", "log", "show", "status", "ls-files", "rev-parse", "blame"}
ADVISOR_GIT_DENIED = ("--output", "--ext-diff", "--textconv", "--open-files-in-pager", "-O")
# Includes brace, glob and tilde expansion, which bash applies before the
# command runs and which could produce words this check never saw.
ADVISOR_SHELL_CHARS = set(";&|<>`$()\\\n\r{}*?[]~")


def advisor_bash_verdict(command: str) -> str | None:
    """Return a deny reason, or None when the advisor may run the command."""
    reason = (
        "Denied: the advisor's Bash runs only `git "
        + "|".join(sorted(ADVISOR_GIT))
        + "`, one command with no pipes, redirects or `;`. "
        "Ask the worker under Fix first to run tests or anything else."
    )
    if any(c in ADVISOR_SHELL_CHARS for c in command):
        return reason
    try:
        words = shlex.split(command)
    except ValueError:
        return reason
    if len(words) >= 2 and words[0] == "git" and words[1] in ADVISOR_GIT:
        return reason if any(_git_arg_denied(w) for w in words[2:]) else None
    return reason


def _git_arg_denied(word: str) -> bool:
    """A denied git option, also as an abbreviation of its long name."""
    if word.startswith(ADVISOR_GIT_DENIED):
        return True
    name = word.split("=", 1)[0]
    return len(name) > 2 and name.startswith("--") and any(
        opt.startswith(name) for opt in ADVISOR_GIT_DENIED if opt.startswith("--")
    )


def on_bash(event: dict) -> None:
    if event.get("tool_name") != "Bash":
        return
    if event.get("agent_id") and not event.get("agent_type"):
        reason = (
            "Denied: this subagent's type is unknown, so its Bash can't be "
            "checked. Run it from the main session or a named subagent."
        )
    elif event.get("agent_type") != ADVISOR_AGENT:
        return
    else:
        command = (event.get("tool_input") or {}).get("command")
        reason = advisor_bash_verdict(command if isinstance(command, str) else "")
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


# The origin kind Claude Code (2.1.332) treats as a person's message, as its
# own rule does (an absent origin counts too). Every other kind (a task or PR
# notification, a channel, a peer, an auto-continuation, a kind added later)
# never starts a turn; that only widens the window, which can add a block but
# never remove one.
HUMAN_ORIGINS = {"human"}
# Fields Claude Code sets on user entries that a tool produced (tool results,
# a loaded skill's text) rather than a new message that starts a turn.
TOOL_DERIVED_KEYS = ("toolUseResult", "sourceToolUseID", "sourceToolAssistantUUID")


def _starts_turn(entry: dict) -> bool:
    """A user entry that opens a turn: a message the person typed.

    System-written entries never start a turn, so none of them can hide the
    work done before it: isMeta (relayed messages, reminders), the
    isCompactSummary entry written after a compaction, a subagent's prompt
    (isSidechain), and any entry whose origin is not a person's (a background
    task or PR notification, for one). Such an entry extends the previous
    turn, which can only add a block, never remove one. The Stop hook's own
    block reason needs no rule here: once a Stop chain starts, on_stop reuses
    the window it stored and never looks for a turn start again.
    """
    if (
        entry.get("type") != "user"
        or entry.get("isMeta")
        or entry.get("isCompactSummary")
        or entry.get("isSidechain")
    ):
        return False
    if any(entry.get(key) is not None for key in TOOL_DERIVED_KEYS):
        return False
    origin = entry.get("origin")
    if origin is not None and (
        not isinstance(origin, dict) or origin.get("kind") not in HUMAN_ORIGINS
    ):
        return False
    content = (entry.get("message") or {}).get("content")
    if not isinstance(content, str):
        blocks = [b for b in content or [] if isinstance(b, dict)]
        if any(b.get("type") == "tool_result" for b in blocks):
            return False
    return True


def turn_start(entries: list[dict]) -> int:
    """Index of the entry that started the current turn, or -1."""
    for i in range(len(entries) - 1, -1, -1):
        if _starts_turn(entries[i]):
            return i
    return -1


def _messages(turn: list[dict]) -> list[list[dict]]:
    """The turn's assistant content blocks, grouped by API message.

    Claude Code writes one entry per content block, so parallel tool calls
    from one message share a message id across several entries. A subagent's
    own entries (isSidechain) are skipped: its work already counts through the
    parent's Agent call, and the advisor's own git reads must not undo its review.
    """
    groups: dict = {}
    for n, entry in enumerate(turn):
        if entry.get("type") != "assistant" or entry.get("isSidechain"):
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


def _advisor_errored(block: dict) -> bool:
    """A built-in advisor result that holds no review.

    Matches how Claude Code itself marks an advisor result as errored: the
    API's error object, or a result (plain or redacted) whose stop reason is
    a refusal, with or without text.
    """
    content = block.get("content")
    if block.get("type") != "advisor_tool_result" or not isinstance(content, dict):
        return False
    if content.get("type") == "advisor_tool_result_error":
        return True
    return (
        content.get("type") in ("advisor_result", "advisor_redacted_result")
        and content.get("stop_reason") == "refusal"
    )


def _is_work(block: dict) -> bool:
    return (
        block.get("type") == "tool_use"
        and not _is_advisor(block)
        and block.get("name") not in NON_WORK_TOOLS
    )


def turn_summary(turn: list[dict]) -> tuple[bool, bool]:
    """(did tool work, consulted the advisor after the last work) for one turn.

    ponytail: any advisor call counts, whatever its verdict. A FIX FIRST that
    is answered with text and no work lets the turn end; the gate makes sure
    the advisor saw the final state, not that its advice was taken. Reading
    the verdict would need the agent's reply format to be a contract.

    An advisor call whose result is an error does not count: no review ran.
    Work clears an earlier advisor call. An advisor call in the same message
    as work does not count, since the two run side by side and the advisor
    cannot see that work's result.
    """
    failed = {
        b.get("tool_use_id")
        for entry in turn
        for b in _blocks(entry)
        if isinstance(b, dict)
        and (
            (
                entry.get("type") == "user"
                and b.get("type") == "tool_result"
                and b.get("is_error")
            )
            or _advisor_errored(b)
        )
    }

    def reviewed(b: dict) -> bool:
        return _is_advisor(b) and not _advisor_errored(b) and b.get("id") not in failed

    worked = consulted = False
    for blocks in _messages(turn):
        if any(_is_work(b) for b in blocks):
            worked, consulted = True, False
        elif any(reviewed(b) for b in blocks):
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


def _state_dir() -> str:
    """A private (0700, owned by us, not a symlink) dir for the Stop counter."""
    path = os.path.join(tempfile.gettempdir(), f"claude-workflow-hooks-{os.getuid()}")
    os.makedirs(path, mode=0o700, exist_ok=True)
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise OSError(f"unsafe state dir {path}")
    return path


def _state_path(event: dict) -> str:
    session = str(event.get("session_id") or event.get("transcript_path"))
    name = hashlib.sha256(session.encode()).hexdigest()[:32] + ".json"
    return os.path.join(_state_dir(), name)


def _chain_state(event: dict, entries: list[dict]) -> tuple[int, int] | None:
    """(turn start index, blocks made so far) for this Stop, or None if unknown.

    A chain is the run of Stops that Claude Code marks stop_hook_active, so it
    starts over with each new turn whatever the transcript holds. The first
    Stop finds the turn start; later Stops in the chain find the same entry by
    the uuid it stored, so however the block reason is written back, it can't
    move the window. If that entry is gone (the transcript was rewritten, as by
    compaction) or had no uuid, the window is the whole transcript, which can
    only add a block.
    """
    if not event.get("stop_hook_active"):
        return turn_start(entries), 0
    try:
        fd = os.open(_state_path(event), os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict):
        return None
    start_uuid, count = state.get("start_uuid"), state.get("blocks")
    if not isinstance(count, int):
        return None
    for i, entry in enumerate(entries):
        if start_uuid is not None and entry.get("uuid") == start_uuid:
            return i, count
    return -1, count


def _record_block(event: dict, entries: list[dict], start: int, count: int) -> bool:
    start_uuid = entries[start].get("uuid") if start >= 0 else None
    try:
        path = _state_path(event)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
        with os.fdopen(os.open(path + ".tmp", flags, 0o600), "w", encoding="utf-8") as fh:
            json.dump({"start_uuid": start_uuid, "blocks": count}, fh)
        os.replace(path + ".tmp", path)
        return True
    except OSError:
        return False


def on_stop(event: dict) -> None:
    path = event.get("transcript_path")
    if not path:
        return
    entries = _read_transcript(path)
    chain = _chain_state(event, entries)
    # Without a working state file, fall back to Claude Code's own one-shot
    # guard so a broken state file can never loop the session.
    if chain is None:
        return
    start, count = chain
    if count >= MAX_STOP_BLOCKS:
        return
    worked, consulted = turn_summary(entries[start + 1 :])
    if not worked or consulted:
        return
    if not _record_block(event, entries, start, count + 1) and event.get("stop_hook_active"):
        return
    _emit(
        {
            "decision": "block",
            "reason": STOP_REASON,
        }
    )


MODES = {"prompt": on_prompt, "subagent": on_subagent, "bash": on_bash, "stop": on_stop}


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
