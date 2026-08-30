# Freeze-lift G0 ×2 — v2107 (2026-08-30)

Measure-only against `https://subnet-dashboard.fly.dev`. Joshua said Go 5:46 PM Arizona.
Do **not** treat this as a pass of PR 1060. Issue 1058 stays closed from 2026-08-27 (`#1071`); this audit does not reopen or re-close it.

Harness: `python harness/g0_hydration_starvation/run_g0.py --base-url https://subnet-dashboard.fly.dev`

## Bar

- Hero complete ≤10s on **both** runs
- `/health` p95 <500ms during burst
- Sequential curl is not closure

## Result: FAIL (both runs STARVATION)

| Run | Captured (UTC) | Hero | Shape | `/health` n/ok | p50 / p95 / p100 | machine |
|-----|----------------|------|-------|----------------|------------------|---------|
| freeze-lift-g0-1 | 00:49:12Z | **NEVER** | STARVATION | 86/85 | 134 / **1245** / 8076 | warm |
| freeze-lift-g0-2 | 00:54:17Z | **NEVER** | STARVATION | 122/120 | 126 / 465 / 8076 | contended |

Both runs: final title `Awaiting subnet`, verdict `cold`, `/api/daily-pick` in aborted hero-critical. Screenshot text: **pick handler busy — retry shortly**. Stats parsed (5.5s / 2.9s) so the hero-critical abort is the pick path, not empty stats.

Run 2 homepage curl sanity TTFB **20087ms** status=None. Immediately after run 2: `/health` 15s timeout, `/api/liveness` **503**. Recovered without restart: `/health` 200 at 00:57:21Z (0.47s) then 0.13s.

## Liveness pair (not the hydration bar)

Ops truth = persisted `/api/liveness`, not `learning_loop_health.last_resolver_tick` (still 17:11Z view skew).

| Read | checked_at | resolver last_success | status | failures | ms |
|------|------------|----------------------|--------|----------|-----|
| T1 | 00:47:34Z | 00:47:19Z | ok | 0 | 18048 |
| T2 | 00:52:48Z | 00:47:19Z (unchanged) | ok | 0 | 16486 |
| T3 | ~00:56Z | **503** (post G0-2 wedge) | — | — | 35807 |

T1→T2 did not advance (~5.5 min, 15m scheduler — not a freeze claim). T3 is burst occupancy, same motif as historical post-offload-prod-2.

Daily pick (pre-G0): GET `/api/daily-pick` 00:30Z `HOLD` `scheduler_hold` reason `daily pick tick timed out after 90s`. Readiness later showed a 00:39Z HOLD with `Directional conflict: council signal is bearish; no LONG published.` Do not bump the 90s cap.

## Standing

- `LOOP_STALL_GUARD_KILL=0`
- PR 1060 remains open (fail-closed)
- No fly-deploy, no restart, no timeout bump
- #1112 / #1113 untouched

Dirs: `artifacts/g0-baseline/freeze-lift-g0-1/` and `freeze-lift-g0-2/` (screenshots + summary; HARs local-only).
