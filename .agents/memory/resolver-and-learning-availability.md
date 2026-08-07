---
name: Resolver & learning endpoint availability
description: Cross-process resolver truth and the expensive weight-delta trail scan that made /api/learning/* time out in prod.
---

## Cross-process resolver state (web never starts the scheduler)
In prod the web process serves HTTP only (`BACKGROUND_ON_WEB=off`); the resolver
scheduler runs in the inline/dedicated worker. So `get_prediction_resolver_scheduler_state()`
inside the web process always reports `running=false` / `last_run_at=null` —
that is **correct**, not a bug. To read the worker's real state, use the
volume-redirecting `internal.learning.loop_health._last_resolver_tick()`; proxy
the `/api/predictions/resolver` endpoint through that so it reflects the worker.

**Why:** Prod health probes hit the web process and its in-memory singleton is
never started, so "resolver down" was a false alarm every time it was checked on
the web VM.

**How to apply:** Any new resolver/learning health metric must read via
`_last_resolver_tick()` (soul-map cycle summary + worker heartbeat), not the
in-process scheduler state, when the code may run on the web process.

## Weight-delta trail scan is expensive — cache it in the learning snapshot
`internal.learning.weight_deltas.recent_expert_weight_deltas()` /
`recent_judge_weight_deltas()` each call `collect_trail_events()`, which merges the
soul map, the prediction ledger, and the dev-signal trail — seconds on a warm
volume when called twice per request. They are now computed once inside the
cached `_learning_snapshot()` (stored as `expert_weight_deltas` /
`judge_weight_deltas` / `expert_graded_counts`) and handlers/callers read them
from the snapshot dict instead of re-scanning.

**Why:** `/api/learning/stats` and `/api/learning/health` timed out / returned 503
because a per-request second-scale blocking scan happened on the event loop.

**How to apply:** These values live in the snapshot now — read from `snap`, do not
call the weight_deltas function form on the request path. Adding another
trail-derived field should follow the same pattern (compute in snapshot, not handler).
