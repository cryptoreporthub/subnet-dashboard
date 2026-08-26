# G0 baseline — `critpath-post-marks-3`

Captured: 2026-08-26T23:27:04.304453Z
Base: https://subnet-dashboard.fly.dev
Shape: **STARVATION**

| Metric | Value |
|--------|-------|
| Hero complete time | 13.921s (budget ≤ 10.0s) |
| stats parsed at | 13.921 |
| hero DOM ready at | 13.921 |
| Final title | `SN55 · NIOME` |
| Final verdict | `sealed` |
| Final graded | `44` / statsGraded=44 |
| Aborted/hung endpoints | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/daily-pick, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/story-path, /api/mindmap/trail, /api/ops/evidence, /api/signals, /api/signals/summary, /api/top-picks, /api/whales/flow-signals |
| Aborted hero-critical | /api/daily-pick |
| /health n / ok | 126 / 125 |
| /health p50 / p95 / p100 | 113.6 / 400.62 / 8034.03 ms |
| /health p95 over 500ms | False |
| Max concurrent in-flight (all / api) | 47 / 28 |
| Pending API still outstanding at t=45s | /api/cockpit/stream, /api/mindmap/trail |
| API request count | 61 |
| Homepage curl TTFB (sanity) | 20047.8 ms status=None |
| machine_state | warm |
| document Server-Timing | app;dur=3.2 |
| html-parse mark (ms) | 120.1 |
| hydrate-start / hydrate-end (ms) | 2680 / 13581.6 |
| stats / daily-pick start (probe s) | 3.015 / 3.015 |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `True`
