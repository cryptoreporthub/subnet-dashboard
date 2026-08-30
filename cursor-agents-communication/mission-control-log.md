# Mission Control log (Ditto-readable)

> **Composer** (Cursor Cloud Agent) operates **all six fleet roles** (Mission Control, Sentinel, Drift/QA, Market Desk, Proof Scout, Shield). Bot-directed tasks route here. **Ditto** remains outside reviewer. **Automation-first:** Joshua delegates merge/deploy authority; routine merges + **`fly-deploy` label** deploys are autonomous unless a PR is explicitly gated (#1088-style behavior change) or policy §3.1 requires human approval.

**Snapshot:** 2026-08-28 ~19:14Z (main `24488f4e` #1107 merged; prod recovering; soak **restarted** 18:52:52Z)

---

## Governance

- **#1080 / #1088 → #1100:** Joshua sign-off **ship it** (2026-08-28). Merged #1100 + deployed; #1088 closed superseded.
- **#1107:** `RESOLVER_CYCLE_TIMEOUT_SECONDS` 120→180 merged `24488f4e`. Deploy **#1108** fly-deploy labeled.
- **Resolver recovery (18:50Z):** persisted stall from 16:56Z cleared. `prediction_resolver=ok`, `consecutive_failures=0`. Ops truth = persisted `/api/liveness` + `/api/ops/readiness` (ignore web `/api/learning/health`).
- **Soak RESTARTED:** 2026-08-28 **18:52:52Z** (first verified clean read post-recovery). **#1072** closes **2026-08-29 18:52:52Z** (~11:52 AM PDT). Prior soak from 15:54Z contaminated (resolver froze 16:56Z).
- **Fleet deploy HOLD:** #1064–#1067 + #1093 on main, **not deployed**. Cut after #1072 closes.
- **#1065 Proof Scout:** already merged `cc734681` (v5 rebase task N/A — on main).

## Standing policy

- Fleet is exactly **six** bots: Mission Control, Sentinel, Drift/QA, Market Desk, Proof Scout, Shield. **No Remedy bot.**
- Policy §3.1: critical findings and live / behavior-changing updates need **human approval only when necessary**.
- Automation-first default: **docs, mirrors, and other non-live changes should proceed automatically when green**; reserve human review for live behavior, safety, or other explicit gates.
- Insights **>4h** are suspect.
- **One PR per bot**, branch `<issue>-<bot>`.
- Canonical refs: `handoffs/bot-fleet-fanout-2026-08-27.md`, `_ci/mission_control_prompt.md`.
- PR **#1082** merged. Do **not** add files to #1082.
- Do **not** route hydrate drafts **#1073 / #1060 / #1061 / #1018**.
- Extra docs PR **#1085** is **not** this fan-out.
- **Pump-alerts preload stays.** No `fly.toml` topology changes.

---

## Closed / resolved

| Item | Resolution |
|------|------------|
| **#1080** Market Desk | **#1100** shipped (was #1088). `trust.ready` gated on `pump_ladder` liveness + signal snapshots. |
| **#1072** Sentinel | **#1089** merged+deployed; formal close after soak ends 2026-08-29 ~15:54Z. |
| **#1078** Drift/QA liveness | Via **#1086** merged 2026-08-28T07:32:58Z (head `6ee50f4b`) |
| **#1079** Drift/QA hour-slot | Via **#1090** merged 2026-08-28T07:33:16Z (head `26067c48`) |
| **#1058** hydration | Live n=3 SHA `ca118843` / Fly `33040064615` |
| **#1081** liveness allowlist | **#1095** daily pick + **#1087** remaining schedulers merged → allowlist `[]` on main `bb142c86` |
| **#1064–#1067** fleet bots | **#1066** Sentinel, **#1065** Proof Scout, **#1067** Shield, **#1064** Market Desk merged 2026-08-28. **#1093** docs merged. |
| **#1029** | Via **#1076 + #1077** |

---

## Phase-5 board

Branches off **main `eb36b0fa`** — last verified 2026-08-28 ~18:35Z.

| Issue | Bot | PR | Status | Notes |
|-------|-----|-----|--------|-------|
| #1072 | Sentinel | **#1089** | **Soak (restarted)** | Clean window from **2026-08-28 18:52:52Z** → close **2026-08-29 18:52:52Z**. |
| #1078 | Drift/QA | **#1086** | **Merged** | Head `6ee50f4b`. |
| #1079 | Drift/QA | **#1090** | **Merged** | Head `26067c48`. |
| #1080 | Market Desk | **#1100** | **Shipped** | Joshua sign-off. `gate_pump_desk_trust` live. |
| #1081 | Proof Scout | **#1087** | **Merged** | Allowlist `[]`. |
| — | Sentinel bot | **#1066** | **Merged** | Read-only health observer. |
| — | Proof Scout bot | **#1065** | **Merged** | Evidence gather; classify only. |
| — | Shield | **#1067** | **Merged** | Abuse detection; approval-gated remediations. |
| — | Market Desk bot | **#1064** | **Merged** | Phase-2 specialist; explain-only. |
| — | Docs | **#1093** | **Merged** | Automation-first governance wording. |

### Remaining (not executed)

- **Sentinel soak → #1072 close** — restarted **2026-08-28 18:52:52Z** → ends **2026-08-29 18:52:52Z** (~11:52 AM PDT).
- **G0 harness ×2 on v2107** — **FAIL** 2026-08-30 ~00:49–00:54Z (both STARVATION). PR 1060 stays open. Issue 1058 already closed 08-27 — not the close target.
- **Resolver watch** — if tick wedges again past 180s cap, capture phase/subsystem delta; do NOT just bump higher (#1107 is mitigation).
- Hydrate drafts **#1073 / #1060 / #1061** untouched.

---

## Mirror duty (Joshua 2026-08-27)

Joshua asked that every Mission Control **user-visible status** be mirrored:

1. **Ditto MCP** — `save_memory` with `source: cursor-agents-communication` / `Mission Control`
2. **This file** — append a dated entry so Ditto can read status from the repo shared folder

**Token-budget rule:** .cursor/rules/token-budget.mdc was deleted **2026-08-16**. Leftover `ditto-sync` / `model-guide` / `subagent-models` lines are intentional — **do not edit in docs-only mirror PRs** unless a change is specifically needed for automation alignment.

**Grok Bot** product prompt (short chat) is **not** in this repo.

---

## Log entries

<!-- Append dated entries below. Newest first. -->

### 2026-08-30 ~00:57 UTC — G0 ×2 on v2107 FAIL (PR 1060 stays open)

- Joshua Go 17:46 AZ. Harness vs live `subnet-dashboard.fly.dev`. **Both** runs STARVATION: hero NEVER, `Awaiting subnet` / COLD, aborted `/api/daily-pick`, UI “pick handler busy — retry shortly”.
- g0-1 00:49Z `/health` p95 **1245ms**. g0-2 00:54Z p95 465ms but homepage curl 20s and post-burst `/health` timeout + liveness **503**. Recovered 00:57:21Z without restart.
- Do not close PR 1060. Issue 1058 already closed 08-27; this is not a re-close. No fly-deploy, KILL=0, no 90s bump.
- Daily pick slot: HOLD after 90s tick timeout (00:17Z) then HOLD directional-conflict (00:39Z). Report: `artifacts/g0-baseline/FREEZE_LIFT_G0.md`.

### 2026-08-29 ~19:00 UTC — FREEZE-LIFT START (hold expired 18:52:52Z / 11:52:52 AM AZ)

- **#1060 reopened** (Ditto): GitHub auto-closed it via keyword match on the substring `close #1060` inside commit `a099999` ("Does not close #1060") at squash-merge 16:54:59Z. Not a G0/liveness pass. Fail-closed marker restored.
- **#1072 soak window COMPLETE** (18:52:52Z → 08-29). GitHub issue already closed 08-28T06:15:52Z via #1089; this is the formal soak close.
- **Post-hold baseline (verified 19:00Z):** resolver fresh 18:53:05Z (age ~7.7min, consec_failures 0); score-snapshot scheduler running, last cycle 18:32:03Z ok count 40 (recovered, advancing); worker peer pid 651 alive (heartbeat 17s); readiness ready, issues []; pump_desk_trust ready; live_cache 149 subnets rpc_healthy. /jobs probe 18:09Z: 7 jobs armed, last_failures {}.
- **QUEUED next:** G0 harness ×2 → #1058 formal close (run both cold-load audits; hero ≤10s + /health p95 <500ms bar). Resolver watch continues via FP7 poll (do NOT bump 180s cap).
- **Standing:** KILL stays 0 (no unmute without explicit ask). Daily pick next slot 00:15Z 08-30.

### 2026-08-28 ~19:14 UTC — v5 delegation: #1107 merge + resolver recovery + soak restart

- **#1107 merged** `24488f4e` (RESOLVER_CYCLE_TIMEOUT_SECONDS 120→180). **#1108** fly-deploy labeled.
- **Incident cleared:** stall from 16:56Z; recovery tick **18:50:55Z**, liveness last **18:59:04Z**.
- **Verify (5 criteria):** (1) resolver=ok ✓ (2) readiness ready, loop ok ✓ (3) tick past 16:56Z ✓ (4) tick advanced stall→18:50→18:59; NOT in final 3-min pair (15m scheduler) — watch next cycle (5) consecutive_failures=0 ✓
- **Soak RESTART:** **2026-08-28 18:52:52Z** → #1072 close **2026-08-29 18:52:52Z**.
- **#1065:** already merged `cc734681`; v5 rebase N/A. Fleet deploy held post-soak.
- **Per-bot:** #1066 merged | #1065 merged | #1067 merged | #1064 merged | #1093 merged — all code-only, not on prod.

### 2026-08-28 ~17:10 UTC — #1102 deploy + #1088 governance ship-it

- **Deploy:** #1103 `fly-deploy` → run **33192921483** success. main `cfa7a5bc`.
- **#1088 gate verified:** `/api/ops/readiness` `pump_desk_trust.ready=true`, `pump_ladder=ok`. `/api/pump-alerts` `trust.liveness.status=ok` but `signal_snapshots_stale=true` (trail placeholder rows — gate working as designed).
- **Learning health:** `status=ok`, resolver `ok`, last tick 16:56Z.
- **Governance:** Joshua sign-off #1088→#1100 ship it.
- **Next:** soak through 2026-08-29 15:54Z → close #1072 → G0×2 → #1058.

### 2026-08-28 ~15:48 UTC — Fleet takeover + Fly deploy (#1098)

- **Policy:** Composer owns all six bot roles; bot-directed work routes to Composer. Deploy via `fly-deploy` label (not Joshua-only).
- **Deploy:** #1098 labeled `fly-deploy`; workflow **33186935806 success** (15:52:44Z). `/api/liveness` confirmed on prod.
- **Soak:** Sentinel 24h watch armed through **2026-08-29 ~15:54Z** (`/health`, `/api/ops/live`, wedge window).
- **Parked:** #1088 human-merge-only (behavior change).

### 2026-08-28 ~15:35 UTC — Deploy is the board choke point (Joshua)

- **Gate:** Fly deploy of `main` `c82c59fe` (human `workflow_dispatch` only). Prod still worker pid 650 — bundle is not just #1089.
- **Then:** Sentinel 24h prod soak → close #1072. Optional G0 ×2 → #1058 formal close.
- **Parked:** #1088 human-merge-only. MC continues routine merges to main; main/prod drift expected until deploy cut.

### 2026-08-28 ~13:05 UTC — #1081 liveness complete (#1095 + #1087)

- **Policy:** Joshua not required for routine merges; Composer verifies no conflict + CI green.
- **Merged:** **#1095** (`ebafd329`) DailyPickScheduler → LivenessTracker; **#1087** (`bb142c86`) remaining 7 schedulers + allowlist `[]`.
- **CI:** smoke green on both PRs (runs 33172947439, 33173497469).
- **Tests:** `test_no_handrolled_liveness`, `test_pick_scheduler`, `test_selector_scheduler`, contract guard — green locally.
- **Parked:** **#1088** Market Desk — human merge only. Deploy not triggered (Fly gated).

### 2026-08-28 ~12:50 UTC — Composer takeover (#1081)

- **Policy:** Joshua not required for routine merges; Composer verifies no conflict + CI green.
- **Done:** `DailyPickScheduler` migrated to `LivenessTracker`; `pick_scheduler.py` removed from liveness allowlist (8→7 modules).
- **Tests:** `test_no_handrolled_liveness`, `test_pick_scheduler`, contract guard — green locally.
- **Branch:** `cursor/1081-daily-pick-liveness-f603` — merged as **#1095**.

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