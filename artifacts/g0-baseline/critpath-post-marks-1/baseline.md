# G0 baseline — `critpath-post-marks-1`

Captured: 2026-08-26T23:15:20.631654Z
Base: https://subnet-dashboard.fly.dev
Shape: **HYDRATES_IN_BUDGET**

| Metric | Value |
|--------|-------|
| Hero complete time | 8.270s (budget ≤ 10.0s) |
| stats parsed at | 8.27 |
| hero DOM ready at | 8.27 |
| Final title | `SN55 · NIOME` |
| Final verdict | `sealed` |
| Final graded | `44` / statsGraded=44 |
| Aborted/hung endpoints | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/graph, /api/mindmap/story-path, /api/signals, /api/signals/summary, /api/top-picks |
| Aborted hero-critical | (none) |
| /health n / ok | 109 / 107 |
| /health p50 / p95 / p100 | 115.57 / 470.41 / 8039.58 ms |
| /health p95 over 500ms | False |
| Max concurrent in-flight (all / api) | 47 / 26 |
| Pending API still outstanding at t=45s | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/story-path, /api/signals, /api/signals/summary, /api/top-picks |
| API request count | 63 |
| Homepage curl TTFB (sanity) | 20048.4 ms status=None |
| machine_state | warm |
| document Server-Timing | app;dur=0.0 |
| html-parse mark (ms) | 151 |
| hydrate-start / hydrate-end (ms) | 4363.1 / 7803.4 |
| stats / daily-pick start (probe s) | 4.71 / 4.71 |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `False`
