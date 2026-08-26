# G0 baseline — `post-p1-reprobe-1`

Captured: 2026-08-26T20:24:21.736254Z
Base: https://subnet-dashboard.fly.dev
Shape: **STARVATION**

| Metric | Value |
|--------|-------|
| Hero complete time | 49.719s (budget ≤ 10.0s) |
| stats parsed at | 49.719 |
| hero DOM ready at | 48.438 |
| Final title | `Closest · SN65 · True Performance Network` |
| Final verdict | `gated` |
| Final graded | `44` / statsGraded=44 |
| Aborted/hung endpoints | /api/cockpit/stream, /api/daily-pick, /api/data-freshness, /api/judges, /api/learning/stats, /api/letter/brain, /api/letter/daily, /api/letter/weekly, /api/market-drivers, /api/message-intel, /api/message-intel/calibration, /api/message-intel/status, /api/mindmap/graph, /api/mindmap/story-path, /api/mindmap/trail, /api/ops/evidence, /api/ops/readiness, /api/portfolio/status, /api/simivision, /api/story-strip, /api/subnet-integrations, /api/subnets, /api/watchlist, /api/whales/flow-signals |
| Aborted hero-critical | /api/daily-pick, /api/learning/stats, /api/daily-pick, /api/daily-pick |
| /health n / ok | 13 / 7 |
| /health p50 / p95 / p100 | 556.58 / 8038.21 / 8039.09 ms |
| /health p95 over 500ms | True |
| Max concurrent in-flight (all / api) | 47 / 28 |
| Pending API still outstanding at t=45s | /api/cockpit/stream, /api/daily-pick, /api/data-freshness, /api/learning/stats, /api/letter/brain, /api/message-intel/calibration, /api/message-intel/status, /api/ops/readiness, /api/portfolio/status, /api/story-strip, /api/subnets, /api/watchlist |
| API request count | 45 |
| Homepage curl TTFB (sanity) | 20049.7 ms status=None |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `True`
