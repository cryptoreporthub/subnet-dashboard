# G0 baseline — `resume-prod-1`

Captured: 2026-08-28T19:51:50.003449Z
Base: https://subnet-dashboard.fly.dev
Shape: **HYDRATES_IN_BUDGET**

| Metric | Value |
|--------|-------|
| Hero complete time | 2.422s (budget ≤ 10.0s) |
| stats parsed at | 2.422 |
| hero DOM ready at | 2.422 |
| Final title | `SN107 · Minos` |
| Final verdict | `sealed` |
| Final graded | `57` / statsGraded=57 |
| Aborted/hung endpoints | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/graph, /api/mindmap/story-path, /api/mindmap/trail, /api/ops/evidence, /api/signals, /api/signals/summary, /api/top-picks, /api/whales/flow-signals |
| Aborted hero-critical | (none) |
| /health n / ok | 136 / 136 |
| /health p50 / p95 / p100 | 127.27 / 411.19 / 5738.28 ms |
| /health p95 over 500ms | False |
| Max concurrent in-flight (all / api) | 47 / 25 |
| Pending API still outstanding at t=45s | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/story-path, /api/signals, /api/signals/summary, /api/top-picks |
| API request count | 59 |
| Homepage curl TTFB (sanity) | 20089.3 ms status=None |
| machine_state | warm |
| document Server-Timing | app;dur=0.0 |
| html-parse mark (ms) | 252.8 |
| hydrate-start / hydrate-end (ms) | 1262.5 / 1663.2 |
| stats / daily-pick start (probe s) | 1.641 / 1.641 |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `False`
