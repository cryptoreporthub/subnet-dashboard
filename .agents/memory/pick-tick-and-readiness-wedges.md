---
name: Pick-tick budget & readiness soft-grading
description: Durable rules behind the three 2026 runtime wedges (daily pick hold, learning-health timeout, readiness hard-block)
---

# Pick-tick budget & readiness soft-grading

These rules stopped three prod wedges where a slow box made status endpoints/actions fail silently.

## Daily pick: feed+context must share the scoring budget
`scheduler.DailyPickScheduler._tick` must do subnet-load + market-context + `get_or_create_today_pick` inside the **one** timed worker thread. Running the feed/context *before* the timer lets blocked egress (feed ≤~25s, macro probes ≤~20s) eat the whole `DAILY_PICK_TICK_TIMEOUT_SECONDS` budget before scoring starts, producing a permanent `scheduler_hold` that never scores.
**Why:** a `scheduler_hold` retries every ~15min but re-times-out identically each time, so the day's pick never forms while the box is slow.
**How to apply:** the `_score()` closure inside `_tick` owns feed+context+pick; keep that shape. Read path must still never call `select_daily_pick` (explicit code comment).

## Learning health: timeout must be cached, not re-run per request
`/api/learning/health` runs `build_learning_loop_health` under `LEARNING_HEALTH_TIMEOUT` (~15s). On timeout it must stash a degraded doc (via `_set_learning_health_degraded_cache`, TTL ~30s) — otherwise every request re-runs a 15s+ build and the endpoint is permanently `source:timeout`.
**Why:** the health build reads predictions/snapshot/soul volumes; on a loaded box it exceeds budget each time, and without caching each request blocks ~15s.
**How to apply:** `_get_cached_learning_health` reads a per-entry `ttl`; tests that touch `/api/learning/health` must reset the module-level `_LEARNING_HEALTH_CACHE` to avoid cross-test pollution.

## Readiness: no-graded-picks is soft, not a hard blocker, when loop is healthy
`learning <= 0` should surface `learning_loop_has_no_graded_picks` as an informational issue and hard-block (`learning_loop_has_no_graded_picks_blocking`) **only** when the loop is genuinely stalled (`loop_health.status == "stalled"` or resolver not running). A healthy-but-young loop with a ticking resolver must keep `ready:true`.
**Why:** a permanent hard block on a low graded count flagged prod not-ready forever while the worker was alive.
**How to apply:** the `ready` gate checks the `*_blocking` suffix, not the bare soft issue; keep the two distinct.
