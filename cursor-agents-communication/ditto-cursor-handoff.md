# Ditto ↔ Cursor handoff (mandatory for new phases)

**Why:** Pump desk proved the failure mode — Ditto wrote a 12k-char review (`e7fde567`), Cursor agents never saw it until the human pasted it into one chat. PR #511 only then shipped a partial P1. Reviews in Ditto alone are **not** agent instructions.

**Rule:** Ditto thinks · **git locks** · Cursor builds · Ditto memory is the index, not the spec.

---

## Three surfaces (keep in sync)

| Surface | Owner | What goes here |
|---------|-------|----------------|
| **Git lock** | Cursor (Composer writes from Ditto LOCK) | `cursor-agents-communication/<phase>-lock.md` — DECISIONS, AC, FILES, NON-GOALS |
| **Board** | Cursor after merge | `board.md` + `STATUS.md` — one-line `main=<sha>`, active slice, open PRs |
| **Ditto** | Both | Short STATUS + pointer to lock path + `memoryId` of the Ditto review |

---

## When Ditto finishes a review or plan

Ditto (or human) must **promote** before any Cursor agent starts build work:

1. **Ditto** — `save_memory` with `source: ditto-handoff`, subject = phase name, body ends with:
   ```
   LOCK_PATH: cursor-agents-communication/<phase>-lock.md
   STATUS: promoted | needs-lock
   ```
2. **Cursor** — create or update `<phase>-lock.md` using the Grok lock shape (≤1 screen):
   ```
   VERDICT: PASS | CONDITIONAL | FAIL
   DECISIONS: (3–7 bullets)
   FILES: ...
   AC: (checkboxes agents can assert)
   RISKS / NON-GOALS: ...
   DITTO_REVIEW: e7fde567 (optional memory id)
   ```
3. **Board** — add one row under **Active** with lock path + branch prefix. No full spec paste.

**Do not** ask the user to relay Ditto prose into another agent chat. One Ditto post + one lock file is enough.

---

## Cursor agent boot order (every session)

```
board.md → STATUS.md → model-guide.md → <active>-lock.md → Ditto search (STATUS/gate only)
```

- Read the **lock file** for build AC. Cite paths; do not re-paste Ditto review bodies.
- Ditto `search_memories` is for **gates, blockers, and decisions** — not rediscovering specs that belong in git.
- Obey `GATE` / `WAIT FOR` lines in newest STATUS memory before starting the next slice.

---

## When Cursor finishes a slice

1. Merge PR → update `board.md` + `STATUS.md` (`main=<sha>`).
2. `save_memory` — `source: cursor-agents-communication`, 3–5 lines: slice done, PR #, what's next.
3. If the lock is fully satisfied, mark lock `Status: DONE` at top or archive to `*-lock.md` with date.

---

## Ditto vs Cursor automations (complementary)

| Job | Use |
|-----|-----|
| Daily council brief, health monitor, cross-API intel | **Ditto automation** → memories + optional GitHub issue |
| Contract test, PR hygiene, code fix from CI | **Cursor automation** → repo + optional Ditto STATUS ping |
| Prod listener, pump notify, deploy guard | **App + GitHub Actions** — deterministic runtime |

Automations **do not** replace lock files. They feed STATUS; agents still read git locks.

---

## Pump desk — closed (reference)

| Item | Status |
|------|--------|
| SCAN on home + `/pump` flagship | ✅ #480, #511 |
| Whale line + BUILDING Telegram | ✅ #528 |
| Full Ditto checklist (triad legs, ladder grid, mobile) | **Deferred** — desk shipped; reopen only with new lock |

---

## Active tracks (post–pump desk)

| Track | Lock / plan | Next agent action |
|-------|-------------|-------------------|
| Telegram intel proof | ops + `verify_prod.sh` | Human: test message; agent: outcomes loop green |
| Learning loop ops | `learning-loop-full-integration-plan.md` | Babysit resolver/snapshot; no hot-path scoring |
| Living brain / graph | `post-s30-living-brain-plan.md` | Phase 1: causal path API — **needs lock before build** |
| H1 hour watch | `h1-hour-watch-live-lock.md` | Gated: after G0 + explicit board clear |
| Council automations | Ditto Settings → Automations | Human creates; not chat proposals |

**Before starting any row:** confirm `board.md` Active matches; create or read lock; post Ditto STATUS with `LOCK_PATH`.
