# Occupancy M7 — runtime capture plan (Patch D OPEN)

**PR:** [#1140](https://github.com/cryptoreporthub/subnet-dashboard/pull/1140) (HOLD / draft). **Do not merge. Do not deploy** until M6 is clean **and** Joshua approves.

**Hypothesis, not measurement:** GIL / TMC-lock convoy. Check 3 must falsify that. GIL cannot be named from these taps.

## What each check produces (once wired)

| # | Check | Tap | Produces | Cannot tap passively |
|---|---|---|---|---|
| 1 | Generation survival | `DailyPickScheduler._tick` timeout → `occupancy_capture.note_timeout` + Timer 5s/60s on `fut.running()` and `daily-pick-*` thread names | `occupancy_capture` JSON + logs `occupancy_capture generation_survival` | py-spy stacks at +5/+60 (M8) |
| 2 | Retry spawn | `note_tick_start(..., overlapping=prev.running())` | `retry_spawn.overlapping_seen` | — |
| 3 | Abandoned-worker block | timed `_tmc_refresh_lock.acquire` wait_ms/held_ms; timed `fcntl.flock` wait_ms | `abandoned_worker_block.tmc_lock` / `.fcntl` samples | **GIL** — `not_passively_observable`; M8 py-spy/faulthandler |
| 4 | Thread-count baseline | first tick records rest count; samples at tick_start | `thread_count.rest_baseline` vs `now` | process RSS / Fly metrics (ops, not this module) |

Read path: `GET /api/learning/health` → `occupancy_capture` (also watchdog/worker logs via `occupancy_capture` warning lines). Price-cache / TMC path is the lock tap on `tmc_singleflight`, not a new HTTP.

## Constraints

90s stays. KILL=0. No load injection. Real traffic only (M8). Ranks 2/3/(e) in this PR remain parked until Patch D (M9). #1112/#1113 untouched. #1060 fail-closed.
