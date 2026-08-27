# G0 baseline — `critpath-graph-defer-1521-1`

Captured: 2026-08-27T02:55:44.058668Z
Base: https://subnet-dashboard.fly.dev
Shape: **HYDRATES_IN_BUDGET**

| Metric | Value |
|--------|-------|
| Hero complete time | 9.518s (budget ≤ 10.0s) |
| stats parsed at | 9.518 |
| hero DOM ready at | 9.518 |
| Final title | `Closest · SN65 · True Performance Network` |
| Final verdict | `gated` |
| Final graded | `46` / statsGraded=46 |
| Aborted/hung endpoints | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/graph, /api/mindmap/story-path, /api/signals, /api/signals/summary, /api/top-picks, /api/whales/flow-signals |
| Aborted hero-critical | (none) |
| /health n / ok | 112 / 111 |
| /health p50 / p95 / p100 | 113.03 / 617.01 / 8035.17 ms |
| /health p95 over 500ms | True |
| Max concurrent in-flight (all / api) | 47 / 21 |
| Pending API still outstanding at t=45s | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/story-path, /api/signals, /api/signals/summary, /api/top-picks |
| API request count | 63 |
| Homepage curl TTFB (sanity) | 20046.4 ms status=None |
| machine_state | warm |
| document Server-Timing | app;dur=0.3 |
| html-parse mark (ms) | 126.3 |
| hydrate-start / hydrate-end (ms) | 2309.8 / 9022.8 |
| stats / daily-pick start (probe s) | 2.793 / 2.793 |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `False`
