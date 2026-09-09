# G0 baseline — `post-offload-prod-1`

Captured: 2026-08-26T21:55:30.785803Z
Base: https://subnet-dashboard.fly.dev
Shape: **STARVATION**

| Metric | Value |
|--------|-------|
| Hero complete time | 12.069s (budget ≤ 10.0s) |
| stats parsed at | 12.069 |
| hero DOM ready at | 12.069 |
| Final title | `Closest · SN65 · True Performance Network` |
| Final verdict | `gated` |
| Final graded | `44` / statsGraded=44 |
| Aborted/hung endpoints | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/graph, /api/mindmap/story-path, /api/signals, /api/signals/summary, /api/top-picks |
| Aborted hero-critical | (none) |
| /health n / ok | 105 / 104 |
| /health p50 / p95 / p100 | 122.11 / 662.8 / 8038.71 ms |
| /health p95 over 500ms | True |
| Max concurrent in-flight (all / api) | 46 / 26 |
| Pending API still outstanding at t=45s | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/story-path, /api/signals, /api/signals/summary, /api/top-picks |
| API request count | 62 |
| Homepage curl TTFB (sanity) | 20049.3 ms status=None |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `True`
