# G0 baseline — `freeze-lift-g0-2`

Captured: 2026-08-30T00:54:17.908345Z
Base: https://subnet-dashboard.fly.dev
Shape: **STARVATION**

| Metric | Value |
|--------|-------|
| Hero complete time | NEVER (budget ≤ 10.0s) |
| stats parsed at | 2.92 |
| hero DOM ready at | None |
| Final title | `Awaiting subnet` |
| Final verdict | `cold` |
| Final graded | `60` / statsGraded=60 |
| Aborted/hung endpoints | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/daily-pick, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/graph, /api/mindmap/story-path, /api/signals, /api/signals/summary, /api/top-picks |
| Aborted hero-critical | /api/daily-pick |
| /health n / ok | 122 / 120 |
| /health p50 / p95 / p100 | 125.77 / 465.15 / 8075.86 ms |
| /health p95 over 500ms | False |
| Max concurrent in-flight (all / api) | 47 / 20 |
| Pending API still outstanding at t=45s | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/daily-pick, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/story-path, /api/signals, /api/signals/summary, /api/top-picks |
| API request count | 69 |
| Homepage curl TTFB (sanity) | 20086.8 ms status=None |
| machine_state | contended |
| document Server-Timing | app;dur=0.0 |
| html-parse mark (ms) | 159.3 |
| hydrate-start / hydrate-end (ms) | 1698.9 / None |
| stats / daily-pick start (probe s) | 2.043 / 2.043 |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `True`
