# Mission Control log (Ditto-readable)

> **Mission Control** is the CEO/orchestrator agent. **Ditto** (GitHub app / heyditto.ai) is the **outside reviewer** — not a fleet bot. **Joshua Riley** (`cryptoreporthub`) is merge/Fly approver. Do not self-merge.

**Snapshot:** 2026-08-28 ~05:40Z (10:40pm PT Aug 27)

---

## Standing policy

- Fleet is exactly **six** bots: Mission Control, Sentinel, Drift/QA, Market Desk, Proof Scout, Shield. **No Remedy bot.**
- Policy §3.1: critical findings need **human approval**.
- Insights **>4h** are suspect.
- **One PR per bot**, branch `<issue>-<bot>`.
- Canonical refs: `handoffs/bot-fleet-fanout-2026-08-27.md`, `_ci/mission_control_prompt.md`.
- PR **#1082** merged. Do **not** add files to #1082.
- Do **not** route leftover PRs **#1064–#1067** or hydrate drafts **#1073 / #1060 / #1061 / #1018**.
- Extra docs PR **#1085** is **not** this fan-out.
- **Pump-alerts preload stays.** No `fly.toml` topology changes.

---

## Closed / resolved

| Item | Resolution |
|------|------------|
| **#1058** hydration | Live n=3 SHA `ca118843` / Fly `33040064615` |
| **#1032** | Via **#1075 + #1077** |
| **#1029** | Via **#1076 + #1077** |

---

## Phase-5 board

Branches off **main `228b9d44`** — re-verify heads if they moved.

| Issue | Bot | PR | Status | Notes |
|-------|-----|-----|--------|-------|
| #1072 | Sentinel | **#1089** | **Ready** (not draft) | Merge **#1089 BEFORE #1086** (shared `internal/health/routes.py`). No fly-deploy. Do **not** rebase 1072 onto 1078. |
| #1078 | Drift/QA | **#1086** | Draft | Unauthenticated GET `/api/liveness` **not** rate-limit exempt. Collides with #1089. |
| #1079 | Drift/QA | **#1090** | Draft | Shield leftover re-audit **CLEARED**, `overall_risk` low. Do **not** merge until Joshua says. |
| #1080 | Market Desk | **#1088** | Draft | Behavior change — **human merge only**. Parked. |
| #1081 | Proof Scout | **#1087** | Draft | Allowlist 9→7. Medium leftovers. Do **not** merge. |

### Proposed merge order (NOT executed)

1. **#1089** first
2. Then rebase **#1086**
3. **#1088** stays parked

---

## Mirror duty (Joshua 2026-08-27)

Joshua asked that every Mission Control **user-visible status** be mirrored:

1. **Ditto MCP** — `save_memory` with `source: cursor-agents-communication` / `Mission Control`
2. **This file** — append a dated entry so Ditto can read status from the repo shared folder

**Token-budget rule:** `.cursor/rules/token-budget.mdc` was deleted **2026-08-16**. Leftover `ditto-sync` / `model-guide` / `subagent-models` lines are intentional — **do not edit in docs-only mirror PRs.**

**Grok Bot** product prompt (short chat) is **not** in this repo.

---

## Log entries

<!-- Append dated entries below. Newest first. -->

### 2026-08-28 ~11:58pm PT / 06:58Z — Step 0 complete: #1091 on main

- Un-drafted #1091, updated branch onto main after #1089+#1085 (head 1fc9386a), smoke green (run 33149466727).
- Squash-merged #1091 at 2026-08-28T06:58:26Z as SHA 4d72a1c385d5c0a2d46057809e564daf85c5b76b. Files: mission-control-log.md, ditto-sync.mdc mirror duty, board.md pointer.
- #1089 already merged (closes #1072). #1085 already merged.
- Next: rebase draft #1086 onto this main; fan-out Sentinel soak, Drift/QA #1090, Market Desk HOLD #1088, Proof Scout #1087 (allowlist 7→0), Shield re-audit.
- No Phase-5 bot PRs merged in this step. #1088 remains parked.

### 2026-08-28 ~05:40Z — Initial snapshot

Phase-5 fan-out board seeded from Mission Control handoff. #1089 ready first; #1086–#1090 remain draft / human-gated. Mirror rule added: `mission-control-log.md` + Ditto `save_memory`.
