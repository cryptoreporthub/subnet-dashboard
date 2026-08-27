# G0 baseline — `critpath-graph-defer-1521-2`

Captured: 2026-08-27T03:00:22.038905Z
Base: https://subnet-dashboard.fly.dev
Shape: **HYDRATES_IN_BUDGET**

| Metric | Value |
|--------|-------|
| Hero complete time | 6.707s (budget ≤ 10.0s) |
| stats parsed at | 6.455 |
| hero DOM ready at | 6.707 |
| Final title | `Closest · SN65 · True Performance Network` |
| Final verdict | `gated` |
| Final graded | `46` / statsGraded=46 |
| Aborted/hung endpoints | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/graph, /api/mindmap/story-path, /api/signals, /api/signals/summary, /api/top-picks |
| Aborted hero-critical | (none) |
| /health n / ok | 130 / 129 |
| /health p50 / p95 / p100 | 120.76 / 518.74 / 8030.88 ms |
| /health p95 over 500ms | True |
| Max concurrent in-flight (all / api) | 47 / 17 |
| Pending API still outstanding at t=45s | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/story-path, /api/signals, /api/signals/summary, /api/top-picks |
| API request count | 59 |
| Homepage curl TTFB (sanity) | 20047.8 ms status=None |
| machine_state | warm |
| document Server-Timing | app;dur=10.6 |
| html-parse mark (ms) | 144.1 |
| hydrate-start / hydrate-end (ms) | 3754.4 / 6299.1 |
| stats / daily-pick start (probe s) | 4.087 / 4.087 |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `False`
