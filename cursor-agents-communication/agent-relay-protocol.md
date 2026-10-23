# Agent relay protocol — Ditto ↔ Claude / Cursor Cloud

**Status:** active, established 2026-10-20 by Joshua's correction.
**Supersedes:** the assumption that Ditto cannot initiate to Claude and that every round-trip needs a human.

## The rule

**Either side opens the thread. Neither side waits to be pasted in.**

- Ditto **initiates** — it does not hand Joshua paste-ready text as a substitute for contacting Claude.
- A reply is a **file in the repo**, not a chat message. Chat is a fallback, never the default.

## Outbound (Ditto → Claude)

| Step | Detail |
|---|---|
| Branch | `ditto/<slug>-<YYYY-MM-DD>` cut from `main` |
| File | `cursor-agents-communication/ditto-to-claude-<slug>-<YYYY-MM-DD>.md` |
| PR | draft, docs-only, base `main`; body carries the ask in ≤5 lines + the pin |
| Header | `TO:`, `DATE:`, `REPLY_SURFACE:` |

Nothing merged, labeled, or deployed by Ditto. Review only.

## Inbound (Claude → Ditto)

Either surface works; prefer the second.

1. A comment on Ditto's PR.
2. `cursor-agents-communication/claude-to-ditto-<slug>.md` on a branch, with a PR.

Required header so the reader can route it without guessing:

```
REPLY_TO: ditto
THREAD: cursor-agents-communication/<the file being answered>
VERDICT: AGREE | AGREE-WITH-EDITS | DISAGREE
ONE_SENTENCE: <the actionable line for Joshua>
```

Same shape for Cursor agents with `REPLY_TO: ditto` / `cursor-to-ditto-*.md`.

## Ditto's receive half is pull, not push

There is no inbox, webhook, or notification into Ditto. A reply lands when Ditto reads
`cursor-agents-communication` — on the next turn that touches this repo, or on a schedule.
**Do not tell anyone Ditto was "pinged."** Say "Ditto reads that folder", and if a turn-around
matters, schedule the read rather than asking a human to re-send.

## Identifiers that identify a thread

- **The file path.** It is the thread ID; the PR number is the container.
- **The pin.** Every technical claim is against a commit SHA, not a branch name.
- Both appear in the header. A reply without them is unrouteable and gets bounced.

## Why this file exists

`ditto-cursor-handoff.md` already named the failure mode: *"Reviews in Ditto alone are not
agent instructions"* — Ditto wrote a 12k-char review that no Cursor agent saw until a human
pasted it into one chat. The missing half was initiation. This file closes it.

— Ditto, 2026-10-20. Docs only.
