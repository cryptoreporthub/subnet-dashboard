# G0 baseline — `critpath-graph-defer-1521-3`

Captured: 2026-08-27T03:05:32.456991Z
Base: https://subnet-dashboard.fly.dev
Shape: **STARVATION**

| Metric | Value |
|--------|-------|
| Hero complete time | 10.886s (budget ≤ 10.0s) |
| stats parsed at | 10.886 |
| hero DOM ready at | 10.886 |
| Final title | `Closest · SN65 · True Performance Network` |
| Final verdict | `gated` |
| Final graded | `46` / statsGraded=46 |
| Aborted/hung endpoints | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/graph, /api/mindmap/story-path, /api/signals, /api/signals/summary, /api/top-picks, /api/whales/flow-signals |
| Aborted hero-critical | (none) |
| /health n / ok | 111 / 110 |
| /health p50 / p95 / p100 | 116.93 / 489.88 / 8033.74 ms |
| /health p95 over 500ms | False |
| Max concurrent in-flight (all / api) | 47 / 18 |
| Pending API still outstanding at t=45s | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/story-path, /api/signals, /api/signals/summary, /api/top-picks |
| API request count | 57 |
| Homepage curl TTFB (sanity) | 20044.6 ms status=None |
| machine_state | warm |
| document Server-Timing | app;dur=0.4 |
| html-parse mark (ms) | 125.1 |
| hydrate-start / hydrate-end (ms) | 2707.8 / 10431.2 |
| stats / daily-pick start (probe s) | 3.046 / 3.045 |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `True`
