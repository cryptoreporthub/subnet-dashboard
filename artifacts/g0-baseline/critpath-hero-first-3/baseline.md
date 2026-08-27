# G0 baseline — `critpath-hero-first-3`

Captured: 2026-08-27T00:21:42.115940Z
Base: https://subnet-dashboard.fly.dev
Shape: **STARVATION**

| Metric | Value |
|--------|-------|
| Hero complete time | NEVER (budget ≤ 10.0s) |
| stats parsed at | 9.869 |
| hero DOM ready at | None |
| Final title | `Awaiting subnet` |
| Final verdict | `cold` |
| Final graded | `45` / statsGraded=45 |
| Aborted/hung endpoints | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/daily-pick, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/graph, /api/mindmap/story-path, /api/signals, /api/signals/summary, /api/top-picks, /api/whales/flow-signals |
| Aborted hero-critical | /api/daily-pick |
| /health n / ok | 128 / 127 |
| /health p50 / p95 / p100 | 110.89 / 480.02 / 8031.49 ms |
| /health p95 over 500ms | False |
| Max concurrent in-flight (all / api) | 47 / 18 |
| Pending API still outstanding at t=45s | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/story-path, /api/signals, /api/signals/summary, /api/top-picks |
| API request count | 63 |
| Homepage curl TTFB (sanity) | 20049.2 ms status=None |
| machine_state | warm |
| document Server-Timing | app;dur=0.3 |
| html-parse mark (ms) | 136.3 |
| hydrate-start / hydrate-end (ms) | 2366.8 / None |
| stats / daily-pick start (probe s) | 2.701 / 2.701 |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `True`
