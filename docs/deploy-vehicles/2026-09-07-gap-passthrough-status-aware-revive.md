# Deploy vehicle — 2026-09-07 · main @ a46441d

Docs-only deploy vehicle. Ships resolver GET `gap_timing_ms` passthrough + status-aware worker-boot revive:

- #1208 — fix(resolver): gap_timing_ms GET passthrough + status-aware boot revive

**Base deployed:** `123328e` (production before this vehicle).
**This vehicle deploys:** `a46441d06056d5847bb0de0b58b7bbadb8951ba1` (merged main with #1208).

Post-deploy verification: `/version` == main short SHA `a46441d`; wait one complete resolver cycle; confirm `last_run_ok: true`, `next_run_at` armed, and `gap_timing_ms` sibling of `stage_timing_ms` with `buckets_ms.preflight|batch_bookkeeping|closing`.
