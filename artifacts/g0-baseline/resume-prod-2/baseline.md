# G0 baseline — `resume-prod-2`

Captured: 2026-08-28T19:56:36.261553Z
Base: https://subnet-dashboard.fly.dev
Shape: **HYDRATES_IN_BUDGET**

| Metric | Value |
|--------|-------|
| Hero complete time | 7.593s (budget ≤ 10.0s) |
| stats parsed at | 7.593 |
| hero DOM ready at | 7.593 |
| Final title | `SN107 · Minos` |
| Final verdict | `sealed` |
| Final graded | `57` / statsGraded=57 |
| Aborted/hung endpoints | /api/cockpit/stream, /api/dev-radar, /api/market-drivers, /api/message-intel, /api/message-intel/authors, /api/message-intel/callers, /api/message-intel/divergence, /api/mindmap/graph, /api/mindmap/story-path, /api/mindmap/trail, /api/ops/evidence, /api/whales/flow-signals |
| Aborted hero-critical | (none) |
| /health n / ok | 84 / 82 |
| /health p50 / p95 / p100 | 147.43 / 1722.82 / 8077.75 ms |
| /health p95 over 500ms | True |
| Max concurrent in-flight (all / api) | 45 / 25 |
| Pending API still outstanding at t=45s | /api/cockpit/stream, /api/message-intel, /api/mindmap/trail |
| API request count | 53 |
| Homepage curl TTFB (sanity) | 118.2 ms status=200 |
| machine_state | warm |
| document Server-Timing | app;dur=72.5 |
| html-parse mark (ms) | 261.3 |
| hydrate-start / hydrate-end (ms) | 5166.8 / 7038.6 |
| stats / daily-pick start (probe s) | 5.511 / 5.511 |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `False`
