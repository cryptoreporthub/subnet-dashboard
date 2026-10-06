# Grok product pipeline queue (repo source of truth)

> **Boot:** read this file first (pinned SHA). Ditto mirrors optional (`grok-product-queue-active-2026-10-06`).
> **Poll:** Grok routine every 3–5 min when `state=WAITING_GROK`; MC routine when `state=WAITING_MC`.

## STATUS

| Field | Value |
|-------|-------|
| `main` | `0293bd2f` |
| `active_slice` | **P2** |
| `state` | `WAITING_MC` |
| `updated` | `2026-10-06T20:00Z` |
| `plan` | `/cursor/stores/self/docs/post-audit-p1-p4-plan.md` |

## Serial queue

| # | Slice | Owner | Branch | State |
|---|-------|-------|--------|-------|
| 1 | P1 universe shrink | Grok | `cursor/p1-universe-shrink-fix` | **DONE** — [PR #1326](https://github.com/cryptoreporthub/subnet-dashboard/pull/1326) Ready @ `7c020112` |
| 2 | P4a resolver lock | Grok | `cursor/p4a-resolver-lock-timeout` | **DONE** — [PR #1327](https://github.com/cryptoreporthub/subnet-dashboard/pull/1327) Ready @ `f4ae56b5` |
| 3 | **P2** F02 Gate C | MC | `cursor/p2-f02-gate-c-receipts-60a6` | **ACTIVE** `WAITING_MC` |
| 4 | P3a council/signals | Grok | `cursor/p3a-council-signals` | queued |
| 5 | P3b chat streaming | Grok | `cursor/p3b-simivision-chat-stream` | queued |
| 6 | P3c message-intel | Grok | `cursor/p3c-message-intel-live` | queued |
| 7 | P4b guard calibrate | Grok | `cursor/p4b-stall-guard-calibrate` | conditional |

---

## P2 handoff (ACTIVE)

**Owner:** MC (docs-only)  
**base:** `main` @ `0293bd2f`  
**branch:** `cursor/p2-f02-gate-c-receipts-60a6`  
**audit anchor:** [PR #1324](https://github.com/cryptoreporthub/subnet-dashboard/pull/1324) pin `ce3d820013d45577333ac8aada8c0d9e97c54129`

**TASK:** F02 Gate C receipts (docs-only):
1. **Static re-run receipt** — re-execute F02 termination-path `git grep` sweep at audit pin; record raw output + exit code.
2. **Gate C prod env receipt** — document effective production env for F02 q12 (`RESOLVER_*`, `LOOP_STALL_GUARD_*`, `WORKER_HEAVY`, etc.) from existing Gate C L2.3 machine-exec evidence (`audit-kit/ledger/ditto-blind-l1l2-results.md`); mark boundaries.

**AC:** two receipt docs under `cursor-agents-communication/audit-kit/evidence/`; draft PR; no product code; no deploy.

---

## P1 report (DONE)

- **PR:** https://github.com/cryptoreporthub/subnet-dashboard/pull/1326
- **head:** `7c020112`
- **MC verdict:** PASS — Ready for review

## P4a report

- **PR:** https://github.com/cryptoreporthub/subnet-dashboard/pull/1327
- **head:** `f4ae56b5`
- **tests:** `test_resolver_revive` + `test_phase3_mid_guards_orphan_revive` + `test_resolver_scheduler` → **56 passed, 2 failed** (legacy `test_revive_recycles_hung_scheduler_and_runs_once`, `test_revive_honest_when_tick_fresh` — **pre-existing on `main`**, not P4a regressions); P4a AC tests (`test_revive_after_cycle_timeout_not_tick_in_progress`, `test_revive_honest_tick_in_progress_when_live_cycle_young`, `test_force_release_cycle_lock_replaces_wedged_lock`) **all passed**; `test_endpoint_contract.py` → **148 passed**
- **code review:** timeout releases `_cycle_lock` via `_force_release_cycle_lock`; revive recycles stale lock via `_resolver_cycle_lock_stale` (no blind `tick_in_progress`); no `RESOLVER_*` env bumps in diff
- **MC verdict:** **PASS** — Ready for review
