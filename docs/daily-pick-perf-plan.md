# Daily Pick Performance: Cache Design & Instrumentation Plan

> Context for Cursor agents: pristine solo run of force_daily_pick.py measured 244+ CPU-seconds / 3,902s wall (~65 min) for one pick over 20 subnets. Stage breakdown: scoring 3,460,697 ms (~95.7%), conviction 14,560 ms, audit 0 ms, predict 1 ms, total 3,614,854 ms. Wall/CPU ratio ~16:1 -> scoring is dominated by waiting (network/chain fetches), not compute. Instrumentation for this plan ships in PR #1020 (internal/council/daily_pick.py).

## Part 1 - Per-Subnet Latency Logging (build first) - DONE via PR #1020

One instrumented run records where the 3,460s concentrates.

Output: data/pick_score_latency.jsonl (JSONL per subnet: ts, run_id, netuid, subnet, score_ms, outcome) plus one summary log line (n, total/median/p90 ms, top-5 slowest).

Decision rule after one instrumented run:
- If >=70% of score_ms comes from <=5 subnets -> cache those subnets' scores aggressively; consider per-subnet timeouts so one slow chain does not dominate.
- If time is evenly spread -> batch/parallelize fetches across subnets (concurrent scoring), which may reduce wall time more than caching does.

## Part 2 - Conviction/Score Cache (mandatory, build second)

Goal: warm rerun of the daily pick costs seconds, not minutes.

- Cache key: (netuid, block_or_epoch). Scores are only valid within the same chain epoch/block window. Stale-key entries are recomputed, never served.
- Storage: data/pick_score_cache.json (or SQLite if concurrent writers matter). Entry: {key, score, inputs_hash, computed_at, ttl_blocks}.
- Hit path: on rerun, load cache -> recompute only stale entries -> proceed to conviction/audit/predict as normal.
- Invalidation: conservative TTL (e.g., current epoch boundary). A wrong cached score is worse than a slow fresh one; when in doubt, miss.
- Concurrency guard: single-writer lock file so multi-process contention cannot produce interleaved cache writes.
- Note: internal/council/score_cache.py exists but is universe-level with 60s TTL (SCORE_CACHE_TTL) - useless for a 65-minute run; do not mistake it for this cache.

## Part 3 - Capacity Work (parallel track, not blocked)

1. Worker=0 consolidation during ticks.
2. Pause MESSAGE_INTEL during tick windows.

These proceed independently of Parts 1-2.

## Sequencing

1. Ship latency logging (Part 1) - small diff, no behavior change. [PR #1020]
2. Run one instrumented pick; collect distribution.
3. Build cache (Part 2) sized to what the data shows.
4. Capacity fixes land alongside whenever ready.
