# G0 baseline — `freeze-lift-g0-1`

Captured: 2026-08-30T00:49:12.874278Z
Base: https://subnet-dashboard.fly.dev
Shape: **STARVATION**

| Metric | Value |
|--------|-------|
| Hero complete time | NEVER (budget ≤ 10.0s) |
| stats parsed at | 5.497 |
| hero DOM ready at | None |
| Final title | `Awaiting subnet` |
| Final verdict | `cold` |
| Final graded | `60` / statsGraded=60 |
| Aborted/hung endpoints | /api/cockpit/stream, /api/daily-pick, /api/message-intel, /api/message-intel/divergence, /api/mindmap/graph, /api/mindmap/story-path, /api/mindmap/trail, /api/ops/evidence, /api/whales/flow-signals |
| Aborted hero-critical | /api/daily-pick |
| /health n / ok | 86 / 85 |
| /health p50 / p95 / p100 | 134.07 / 1245.46 / 8076.36 ms |
| /health p95 over 500ms | True |
| Max concurrent in-flight (all / api) | 47 / 21 |
| Pending API still outstanding at t=45s | /api/cockpit/stream, /api/message-intel/trending-v2, /api/mindmap/trail |
| API request count | 55 |
| Homepage curl TTFB (sanity) | 118.2 ms status=200 |
| machine_state | warm |
| document Server-Timing | app;dur=0.0 |
| html-parse mark (ms) | 597.4 |
| hydrate-start / hydrate-end (ms) | 4685.8 / None |
| stats / daily-pick start (probe s) | 5.066 / 5.065 |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `True`
