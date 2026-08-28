# Mission Control log (Ditto-readable)

> **Mission Control** is the CEO/orchestrator agent. **Ditto** (GitHub app / heyditto.ai) is the **outside reviewer** — not a fleet bot. **Joshua Riley** (`cryptoreporthub`) is merge/Fly approver. Do not self-merge.

**Snapshot:** 2026-08-28 ~09:22Z (2:22am PT Aug 28)

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
| **#1072** Sentinel zoom | Closed via **#1089** merged 2026-08-28T06:15:51Z |
| **#1078** Drift/QA liveness | Via **#1086** merged 2026-08-28T07:32:58Z (head `6ee50f4b`) |
| **#1079** Drift/QA hour-slot | Via **#1090** merged 2026-08-28T07:33:16Z (head `26067c48`) |
| **#1058** hydration | Live n=3 SHA `ca118843` / Fly `33040064615` |
| **#1032** | Via **#1075 + #1077** |
| **#1029** | Via **#1076 + #1077** |

---

## Phase-5 board

Branches off **main `98677e74`** — last verified 2026-08-28 ~09:22Z.

| Issue | Bot | PR | Status | Notes |
|-------|-----|-----|--------|-------|
| #1072 | Sentinel | **#1089** | **Merged** | Closes #1072. Merged 2026-08-28T06:15:51Z. Sentinel soak: `/health` 200, `/api/ops/live` ok `live=true`; one recovered 20s timeout. Fly pid 650 — #1089 likely not deployed. |
| #1078 | Drift/QA | **#1086** | **Merged** | Head `6ee50f4b`. Leak patch: `public_liveness_registry` strips `last_error`/`last_evidence`; GET `/api/liveness` `probe_worker=False`. Coordinator leftovers (`last_run_ok`/`force_running`/`pump_desk_trust.ready`) landed as-is. |
| #1079 | Drift/QA | **#1090** | **Merged** | Head `26067c48`. HourPickScheduler + `loop_health` on tracker. DailyPickScheduler on main **still** has `_running`/`_last_run_at`/`_last_ok` — fails #1087 empty-allowlist smoke. |
| #1080 | Market Desk | **#1088** | **Draft HOLD** | Shield FINAL: human merge only. Extra placeholder trail-phase gate. Smoke does not run `test_pump_desk_trust_gate.py`. Head `185f536`. Base may still be behind. |
| #1081 | Proof Scout | **#1087** | **Draft** | Head `ef3ae950`. Allowlist `[]`. 17 files. `pick_scheduler.py` zero vs main (collision cleared). Selector/calibration leftovers cleaned; six other schedulers leftover-cleaned per Shield. Smoke **FAIL**: DailyPickScheduler `_running` still on main. Security empty. Nested snapshots note only, not §3.1. |

### Remaining (not executed)

- **#1087** Proof Scout — draft; smoke FAIL until DailyPickScheduler leftover on main addressed. Joshua skipped daily-pick follow-on widget — **do not** claim a follow-on PR is open.
- **#1088** Market Desk — DRAFT HOLD; human merge only.
- Leftover PRs **#1064–#1067** and hydrate drafts untouched.

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

### 2026-08-28 ~12:50 UTC — Composer takeover (#1081)

- **Policy:** Joshua not required for routine merges; Composer verifies no conflict + CI green.
- **Done:** `DailyPickScheduler` migrated to `LivenessTracker`; `pick_scheduler.py` removed from liveness allowlist (8→7 modules).
- **Tests:** `test_no_handrolled_liveness`, `test_pick_scheduler`, contract guard — green locally.
- **Branch:** `cursor/1081-daily-pick-liveness-f603` — PR pending merge (main is branch-protected).
- **Next:** merge #1081 PR → Luna spot-check → post-deploy G0 ×2 if Joshua wants #1058 formally closed on issue.

- Ditto MCP has all beats; this file was stale after Step 0 (#1092). Catch-up append per Joshua: are all MC messages in the shared repo?
- Board tables refreshed to main `98677e74`.

### 2026-08-28 ~2:22am PT — Sentinel soak (post-#1089 merge)

- `/health` 200, `/api/ops/live` ok `live=true`, homepage desktop+390px 200.
- One recovered 20s ops/live timeout.
- Fly pid 650 unchanged — #1089 on main likely not on the machine. **No deploy.**
- 24h wedge watch armed through 2026-08-28 23:59 PT.

### 2026-08-28 ~1:06–1:08am PT — #1086+#1090 on main

- #1086 merged 2026-08-28T07:32:58Z (head `6ee50f4b`). #1090 merged 2026-08-28T07:33:16Z (head `26067c48`).
- Main SHA verified `98677e74` includes both.
- #1087 `ef3ae950`: leftover cleanup confirmed; `pick_scheduler.py` zero vs main.
- DailyPickScheduler `_running`/`_last_run_at`/`_last_ok` still on main — fails #1087 empty-allowlist smoke.
- Joshua skipped daily-pick follow-on widget; **do not** claim a follow-on is open.

### 2026-08-28 ~12:22am PT — #1087 collision cleared

- Collision cleared at `5c74d609`, then leftover cleanup per Shield.
- Shield re-audits #1087.

### 2026-08-28 ~12:10–12:17am PT — #1086 leak patch

- Leak patch head `6ee50f4b`; smoke green.
- Leak HOLD closed.

### 2026-08-28 ~12:04–12:08am PT — Shield FINAL on #1088; #1090 smoke green; #1086 rebase

- #1088 Shield FINAL HOLD (human merge only).
- #1090 smoke green.
- #1086 rebase done `e6d928df` then leak patch applied.

### 2026-08-28 ~11:58pm PT / 06:58Z — Step 0 complete: #1091 on main

- Un-drafted #1091, updated branch onto main after #1089+#1085 (head 1fc9386a), smoke green (run 33149466727).
- Squash-merged #1091 at 2026-08-28T06:58:26Z as SHA 4d72a1c385d5c0a2d46057809e564daf85c5b76b. Files: mission-control-log.md, ditto-sync.mdc mirror duty, board.md pointer.
- #1089 already merged (closes #1072). #1085 already merged.
- Next: rebase draft #1086 onto this main; fan-out Sentinel soak, Drift/QA #1090, Market Desk HOLD #1088, Proof Scout #1087 (allowlist 7→0), Shield re-audit.
- No Phase-5 bot PRs merged in this step. #1088 remains parked.

### 2026-08-28 ~05:40Z — Initial snapshot

Phase-5 fan-out board seeded from Mission Control handoff. #1089 ready first; #1086–#1090 remain draft / human-gated. Mirror rule added: `mission-control-log.md` + Ditto `save_memory`.
