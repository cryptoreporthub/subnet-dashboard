# G0 baseline — `critpath-post-marks-2`

Captured: 2026-08-26T23:21:21.051889Z
Base: https://subnet-dashboard.fly.dev
Shape: **STARVATION**

| Metric | Value |
|--------|-------|
| Hero complete time | 13.881s (budget ≤ 10.0s) |
| stats parsed at | 13.626 |
| hero DOM ready at | 13.881 |
| Final title | `SN55 · NIOME` |
| Final verdict | `gated` |
| Final graded | `44` / statsGraded=44 |
| Aborted/hung endpoints | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/daily-pick, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/graph, /api/mindmap/story-path, /api/mindmap/trail, /api/ops/evidence, /api/signals, /api/signals/summary, /api/top-picks, /api/whales/flow-signals |
| Aborted hero-critical | /api/daily-pick |
| /health n / ok | 135 / 135 |
| /health p50 / p95 / p100 | 123.15 / 463.12 / 7938.24 ms |
| /health p95 over 500ms | False |
| Max concurrent in-flight (all / api) | 47 / 27 |
| Pending API still outstanding at t=45s | /api/cockpit/stream, /api/mindmap/trail |
| API request count | 59 |
| Homepage curl TTFB (sanity) | 20047.3 ms status=None |
| machine_state | warm |
| document Server-Timing | app;dur=21.0 |
| html-parse mark (ms) | 145.3 |
| hydrate-start / hydrate-end (ms) | 4863.5 / 13476.3 |
| stats / daily-pick start (probe s) | 5.184 / 5.184 |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `True`
