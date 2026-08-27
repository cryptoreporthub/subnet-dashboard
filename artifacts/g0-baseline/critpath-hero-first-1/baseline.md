# G0 baseline — `critpath-hero-first-1`

Captured: 2026-08-27T00:10:21.162623Z
Base: https://subnet-dashboard.fly.dev
Shape: **HYDRATES_IN_BUDGET**

| Metric | Value |
|--------|-------|
| Hero complete time | 4.248s (budget ≤ 10.0s) |
| stats parsed at | 4.248 |
| hero DOM ready at | 4.248 |
| Final title | `Closest · SN65 · True Performance Network` |
| Final verdict | `gated` |
| Final graded | `45` / statsGraded=45 |
| Aborted/hung endpoints | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/graph, /api/mindmap/story-path, /api/signals, /api/signals/summary, /api/top-picks |
| Aborted hero-critical | (none) |
| /health n / ok | 118 / 116 |
| /health p50 / p95 / p100 | 114.78 / 439.78 / 8034.23 ms |
| /health p95 over 500ms | False |
| Max concurrent in-flight (all / api) | 47 / 18 |
| Pending API still outstanding at t=45s | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/signals, /api/signals/summary, /api/top-picks |
| API request count | 64 |
| Homepage curl TTFB (sanity) | 20046.8 ms status=None |
| machine_state | warm |
| document Server-Timing | app;dur=0.4 |
| html-parse mark (ms) | 127.8 |
| hydrate-start / hydrate-end (ms) | 1627.2 / 3880.5 |
| stats / daily-pick start (probe s) | 1.958 / 1.958 |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `False`
