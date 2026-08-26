# G0 baseline — `prod-2`

Captured: 2026-08-26T17:55:35.914486Z
Base: https://subnet-dashboard.fly.dev
Shape: **STARVATION**

| Metric | Value |
|--------|-------|
| Hero complete time | NEVER (budget ≤ 10.0s) |
| stats parsed at | None |
| hero DOM ready at | None |
| Final title | `Awaiting subnet` |
| Final verdict | `cold` |
| Final graded | `0` / statsGraded=None |
| Aborted/hung endpoints | /api/cockpit/stream, /api/daily-pick, /api/data-freshness, /api/dev-radar, /api/judges, /api/learning/stats, /api/letter/brain, /api/letter/daily, /api/letter/weekly, /api/market-drivers, /api/message-intel/calibration, /api/message-intel/status, /api/mindmap/graph, /api/mindmap/story-path, /api/mindmap/trail, /api/ops/evidence, /api/ops/readiness, /api/portfolio/status, /api/pump-alerts, /api/simivision, /api/story-strip, /api/subnet-integrations, /api/subnets, /api/watchlist, /api/whales/flow-signals |
| Aborted hero-critical | /api/daily-pick, /api/learning/stats, /api/daily-pick, /api/daily-pick, /api/learning/stats, /api/daily-pick |
| /health n / ok | 15 / 9 |
| /health p50 / p95 / p100 | 559.09 / 8037.93 / 8038.8 ms |
| /health p95 over 500ms | True |
| Max concurrent in-flight (all / api) | 46 / 28 |
| Pending API still outstanding at t=45s | /api/cockpit/stream, /api/daily-pick, /api/data-freshness, /api/dev-radar, /api/learning/stats, /api/letter/brain, /api/message-intel/calibration, /api/message-intel/status, /api/ops/readiness, /api/portfolio/status, /api/pump-alerts, /api/story-strip, /api/subnets, /api/watchlist |
| API request count | 42 |
| Homepage curl TTFB (sanity) | 20048.7 ms status=None |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `True`
