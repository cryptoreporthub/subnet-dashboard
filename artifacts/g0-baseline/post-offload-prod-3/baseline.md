# G0 baseline — `post-offload-prod-3`

Captured: 2026-08-26T22:00:39.726051Z
Base: https://subnet-dashboard.fly.dev
Shape: **STARVATION**

| Metric | Value |
|--------|-------|
| Hero complete time | 15.245s (budget ≤ 10.0s) |
| stats parsed at | 15.245 |
| hero DOM ready at | 15.245 |
| Final title | `Closest · SN65 · True Performance Network` |
| Final verdict | `gated` |
| Final graded | `44` / statsGraded=44 |
| Aborted/hung endpoints | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/message-intel, /api/mindmap/graph, /api/mindmap/story-path, /api/signals, /api/signals/summary, /api/top-picks |
| Aborted hero-critical | (none) |
| /health n / ok | 107 / 106 |
| /health p50 / p95 / p100 | 129.22 / 550.36 / 8036.08 ms |
| /health p95 over 500ms | True |
| Max concurrent in-flight (all / api) | 47 / 26 |
| Pending API still outstanding at t=45s | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/story-path, /api/signals, /api/signals/summary, /api/top-picks |
| API request count | 60 |
| Homepage curl TTFB (sanity) | 20050.6 ms status=None |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `True`
