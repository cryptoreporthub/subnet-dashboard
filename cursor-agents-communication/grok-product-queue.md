# Grok product queue (autonomous pipeline)

**Updated:** 2026-10-06  
**Bus:** Ditto primary + this repo mirror

## STATUS

```yaml
slice: P4a
state: WAITING_MC
prev_slice: P1
prev_verdict: PASS
base: main @ 245ff24e
branch: cursor/p4a-resolver-lock-timeout
head: 7495dbce
report_vendorId: grok-p4a-resolver-lock-report-2026-10-06
handoff_vendorId: grok-p4a-resolver-lock-handoff-2026-10-06
```

## Queue

| # | ID | Branch | State |
|---|-----|--------|-------|
| 1 | P1 | `cursor/p1-universe-shrink-fix` | MC reviewed PASS |
| 2 | **P4a** | `cursor/p4a-resolver-lock-timeout` | **WAITING_MC** |
| 3 | P2 | `cursor/p2-f02-gate-c-receipts` | MC-owned |
| 4 | P3a | `cursor/p3a-council-signals` | queued |
| 5 | P3b | `cursor/p3b-simivision-chat-stream` | queued |
| 6 | P3c | `cursor/p3c-message-intel-live` | queued |
| 7 | P4b | `cursor/p4b-stall-guard-calibrate` | conditional |

## P4a report

**PR:** https://github.com/cryptoreporthub/subnet-dashboard/pull/1327 (draft)  
**Head SHA:** `4931165a960292bb550d1d184c5071fabed9fdbc`  
**Base:** `main` @ `245ff24e`

### Problem

Resolver cycles overrun the 360s timeout budget. After abandon, `_cycle_lock` could remain wedged so `revive_prediction_resolver_scheduler` returned `tick_in_progress` (`resolver_scheduler.py:1351-1357`), preventing loop stall guard recovery.

### Fix

- `_force_release_cycle_lock()` — release or replace wedged lock after `cycle_abandon`
- Timeout `finally` clears done `_inflight_future`
- Revive recycles when lock is stale (`abandoned_live > 0`, tick age > cycle budget, or wedged with no live worker)

### Tests

| Suite | Result |
|-------|--------|
| `pytest tests/test_resolver_revive.py tests/test_phase3_mid_guards_orphan_revive.py tests/test_resolver_scheduler.py` | **56 passed**, 2 pre-existing failures (liveness registry `age_after` / `tick_fresh`; same on base `245ff24e`) |
| `pytest tests/test_endpoint_contract.py` | **148 passed** |

No `RESOLVER_*` env bumps. No deploy.
