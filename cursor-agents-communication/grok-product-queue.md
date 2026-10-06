# Grok product pipeline queue (repo source of truth)

> **Boot:** read this file first (pinned SHA). Ditto mirrors optional (`grok-product-queue-active-2026-10-06`).
> **Poll:** Grok routine every 3–5 min when `state=WAITING_GROK`; MC routine when `state=WAITING_MC`.

## STATUS

| Field | Value |
|-------|-------|
| `main` | `0293bd2f` |
| `active_slice` | **P3a** |
| `state` | `WAITING_GROK` |
| `updated` | `2026-10-06T20:55Z` |
| `plan` | `/cursor/stores/self/docs/post-audit-p1-p4-plan.md` |

## Serial queue

| # | Slice | Owner | Branch | State |
|---|-------|-------|--------|-------|
| 1 | P1 universe shrink | Grok | `cursor/p1-universe-shrink-fix` | **DONE** — [PR #1326](https://github.com/cryptoreporthub/subnet-dashboard/pull/1326) Ready @ `7c020112` |
| 2 | P4a resolver lock | Grok | `cursor/p4a-resolver-lock-timeout` | **DONE** — [PR #1327](https://github.com/cryptoreporthub/subnet-dashboard/pull/1327) Ready @ `f4ae56b5` |
| 3 | P2 F02 Gate C | MC | `cursor/p2-f02-gate-c-receipts-60a6` | **DONE** — [PR #1328](https://github.com/cryptoreporthub/subnet-dashboard/pull/1328) Ready @ `a862121d` |
| 4 | **P3a** council/signals | Grok | `cursor/p3a-council-signals` | **ACTIVE** `WAITING_GROK` |
| 5 | P3b chat streaming | Grok | `cursor/p3b-simivision-chat-stream` | queued |
| 6 | P3c message-intel | Grok | `cursor/p3c-message-intel-live` | queued |
| 7 | P4b guard calibrate | Grok | `cursor/p4b-stall-guard-calibrate` | conditional |

---

## P3a handoff (ACTIVE)

**Owner:** Grok  
**handoff vendorId:** `grok-p3a-council-signals-handoff-2026-10-06`  
**report vendorId:** `grok-p3a-council-signals-report-2026-10-06`  
**base:** `main` @ `0293bd2f`  
**branch:** `cursor/p3a-council-signals`  
**audit anchor:** [PR #1324](https://github.com/cryptoreporthub/subnet-dashboard/pull/1324) pin `ce3d820013d45577333ac8aada8c0d9e97c54129`

**PROBLEM:** G0 prod repro (`artifacts/g0-baseline/`, `g0-1058-composer-p1-handoff.md`) showed `/api/daily-pick` aborting under homepage hydrate burst and `/health` starvation from request-path occupancy. Rev3 triage checklist #7 (signal cross-check @ incident timestamp) was **PARTIAL** — council busy/empty, endpoints timed out → NOT_OBSERVABLE. Council signal workers (`internal/council/signals/{poller,pathfinder}.py`) are stubs; reliability must come from the existing signal pipeline + read-path guards.

**TASK — council/signals/daily-pick reliability:**
1. **Daily-pick hydrate GET** — cached-today hit returns within tight budget without `get_or_create_today_pick` / full scoring (`server.py` `api_daily_pick`, coalesced flight). Timeout HOLD must carry `_meta.stale:true` and must not masquerade as scheduler HOLD.
2. **Homepage/council read paths** — verify no remaining hydrate callers invoke `get_or_create_today_pick` (`internal/learning/dashboard_context.py`, `_home_hero_context`, `_pick_sections`). Read stored JSON only.
3. **Signals under load** — `/api/signals` + `/api/signals/summary` return honest-empty or cached payload fast; no naked busy hang without degraded marker when executor saturated.
4. **Pick scheduler guard** — confirm `pick_scheduler` generation/`is_cancelled` abort before `_save` (L6-002 pattern); add test if gap found.

**FILES (likely):** `server.py`, `internal/learning/dashboard_context.py`, `internal/council/pick_scheduler.py`, `internal/council/daily_pick_engine.py`, `internal/signals/routes.py`, `tests/test_api_handler_timeouts.py`, `tests/test_homepage_pick_read_only.py`

**AC:** targeted pytest green; `test_endpoint_contract.py` green; draft PR + Ditto report (`grok-p3a-council-signals-report-2026-10-06`); no deploy; no `fly.toml` / `RESOLVER_*` env bumps.

**Reference:** `cursor-agents-communication/g0-1058-composer-p1-handoff.md` §A–C (occupancy root cause — do not re-score on GET).

---

## P2 report (DONE)

- **PR:** https://github.com/cryptoreporthub/subnet-dashboard/pull/1328
- **head:** `a862121d`
- **artifacts:** `audit-kit/evidence/f02-static-rerun-receipt-2026-10-06.md`, `audit-kit/evidence/f02-gate-c-prod-env-receipt-2026-10-06.md`
- **AC review:** docs-only (2 files, +109 lines); audit pin `ce3d8200…` correct; static sweep re-verified (58 matches, exit 0); Gate C env receipt PARTIAL PASS with honest NOT_OBSERVABLE fences for silent guard knobs
- **MC verdict:** **PASS** — Ready for review

## P1 report (DONE)

- **PR:** https://github.com/cryptoreporthub/subnet-dashboard/pull/1326
- **head:** `7c020112`
- **MC verdict:** PASS — Ready for review

## P4a report (DONE)

- **PR:** https://github.com/cryptoreporthub/subnet-dashboard/pull/1327
- **head:** `f4ae56b5`
- **tests:** `test_resolver_revive` + `test_phase3_mid_guards_orphan_revive` + `test_resolver_scheduler` → **56 passed, 2 failed** (legacy `test_revive_recycles_hung_scheduler_and_runs_once`, `test_revive_honest_when_tick_fresh` — **pre-existing on `main`**, not P4a regressions); P4a AC tests (`test_revive_after_cycle_timeout_not_tick_in_progress`, `test_revive_honest_tick_in_progress_when_live_cycle_young`, `test_force_release_cycle_lock_replaces_wedged_lock`) **all passed**; `test_endpoint_contract.py` → **148 passed**
- **code review:** timeout releases `_cycle_lock` via `_force_release_cycle_lock`; revive recycles stale lock via `_resolver_cycle_lock_stale` (no blind `tick_in_progress`); no `RESOLVER_*` env bumps in diff
- **MC verdict:** **PASS** — Ready for review
