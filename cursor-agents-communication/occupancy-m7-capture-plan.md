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

## REVIEW-ADOPTED SCOPE (MANDATORY) — 2026-08-30

1. **Check 5 — stale-generation internal side effects.** Detect JSON / HOLD / prediction / learning / cache writes performed by a timed-out/stale generation AFTER the outer timeout and BEFORE the generation check. If the write sites expose no timestamps, report `stale_side_effects: not_observable` WITH an explicit reason so "we checked and found nothing" is distinguishable from "we didn't check": use `reason: checked; no timestamp at write sites` versus `reason: not captured`. Same rule as `deployment_identity: unknown`.

2. **Deployment & process provenance in occupancy_capture.** Capture: active production release/deployed commit; process start time; PID/worker identity; VM size/topology and region; worker config; whether the running release includes the #1008 merge. If unavailable: `deployment_identity: unknown` — never a pass or an inferred match. Check 4's thread baseline is uninterpretable without live VM identity.

3. **Evidence contract per check.** Record at minimum: UTC timestamp · generation ID · worker/thread identity · scheduler tick + retry timestamps · timeout/abandonment/completion events · thread count before/during/after overlap · executor occupancy · TMC lock wait/held evidence · endpoint latency/status · deployment identity. Grading is pass / fail / inconclusive only — null or absent fields never count as pass.

4. **Worker-log correlation.** Capture and correlate in the same evidence window: `daily tick timed out` · `worker abandoned` · `retry scheduled/started` · `generation started/completed` · lock wait/held events · thread/executor occupancy. If worker logs are unavailable in the window, check 3 reports `inconclusive` — never interpreted from health data alone.

**Constraints (unchanged):** passive observers only, NO behavior/timing change, no load injection, 90s timeout stays, KILL=0, no #1060/scheduler changes. All 181 existing tests must stay green; add tests for the new fields. HOLD/draft maintained — do NOT request merge.