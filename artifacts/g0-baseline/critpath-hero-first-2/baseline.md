# G0 baseline — `critpath-hero-first-2`

Captured: 2026-08-27T00:15:05.436326Z
Base: https://subnet-dashboard.fly.dev
Shape: **STARVATION**

| Metric | Value |
|--------|-------|
| Hero complete time | 14.774s (budget ≤ 10.0s) |
| stats parsed at | 11.492 |
| hero DOM ready at | 14.774 |
| Final title | `Closest · SN65 · True Performance Network` |
| Final verdict | `gated` |
| Final graded | `45` / statsGraded=45 |
| Aborted/hung endpoints | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/graph, /api/mindmap/story-path, /api/signals, /api/signals/summary, /api/top-picks |
| Aborted hero-critical | (none) |
| /health n / ok | 118 / 117 |
| /health p50 / p95 / p100 | 116.84 / 545.45 / 8034.02 ms |
| /health p95 over 500ms | True |
| Max concurrent in-flight (all / api) | 47 / 17 |
| Pending API still outstanding at t=45s | /api/alerts, /api/backtest, /api/cockpit/sections, /api/cockpit/stream, /api/formula-lineage, /api/formula-lineage/dark_horse/evolution, /api/indicators-convergence, /api/mindmap/story-path, /api/signals, /api/signals/summary, /api/top-picks |
| API request count | 60 |
| Homepage curl TTFB (sanity) | 20054.0 ms status=None |
| machine_state | contended |
| document Server-Timing | app;dur=0.3 |
| html-parse mark (ms) | 144.4 |
| hydrate-start / hydrate-end (ms) | 3818.6 / 14213.7 |
| stats / daily-pick start (probe s) | 4.147 / 4.146 |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `True`
