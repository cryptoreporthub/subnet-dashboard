# Mission Control log (Ditto-readable)

> **Composer** (Cursor Cloud Agent) operates **all six fleet roles** (Mission Control, Sentinel, Drift/QA, Market Desk, Proof Scout, Shield). Bot-directed tasks route here. **Ditto** remains outside reviewer. **Automation-first:** Joshua delegates merge/deploy authority; routine merges + **`fly-deploy` label** deploys are autonomous unless a PR is explicitly gated (#1088-style behavior change) or policy §3.1 requires human approval.

**Snapshot:** 2026-08-28 ~18:35Z (main `eb36b0fa`; prod **#1102** live via #1103; fleet bots merged, not yet deployed)

---

## Governance

- **#1080 / #1088 → #1100:** Joshua sign-off **ship it** (2026-08-28). Merged #1100 + deployed; #1088 draft closed superseded.
- **#1088 gate live:** `pump_desk_trust.ready=true`, `pump_ladder=ok` on `/api/ops/readiness`. Full desk path (`/api/pump-alerts`) also requires non-placeholder signal snapshots — currently `signal_snapshots_stale=true` (expected until ladder scan refreshes trail rows).
- **Sentinel soak:** armed 2026-08-28 ~15:54Z → **close #1072** after clean window **2026-08-29 ~15:54Z** (~8:54 AM PDT). Then G0×2 → close **#1058**.
- **Resolver watch:** prod resolver `failing` (persisted, last tick 16:56Z). `/api/liveness` may timeout under load — use `/api/ops/readiness` persisted trackers for soak truth. Bump `RESOLVER_CYCLE_TIMEOUT_SECONDS` if `cycle_timeout_120s` recurs.
- **Fleet queue (2026-08-28):** **#1066** Sentinel → **#1065** Proof Scout → **#1067** Shield → **#1064** Market Desk → **#1093** docs — **all merged** to main `eb36b0fa`. Read-only bots; no new routes. Deploy when convenient.

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
| #1072 | Sentinel | **#1089** | **Soak** | Formal close after 2026-08-29 ~15:54Z. |
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

- **Sentinel soak → #1072 close** — window ends **2026-08-29 ~15:54Z** (~8:54 AM PDT).
- **G0 harness ×2 → #1058 formal close** — after soak.
- **Resolver timeout watch** — bump `RESOLVER_CYCLE_TIMEOUT_SECONDS` if 120s cap keeps firing.
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
