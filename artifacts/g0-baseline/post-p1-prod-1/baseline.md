# G0 baseline — `post-p1-prod-1`

Captured: 2026-08-26T19:31:43.755805Z
Base: https://subnet-dashboard.fly.dev
Shape: **STARVATION**

| Metric | Value |
|--------|-------|
| Hero complete time | NEVER (budget ≤ 10.0s) |
| stats parsed at | None |
| hero DOM ready at | 35.962 |
| Final title | `Closest · SN97 · Albedo` |
| Final verdict | `gated` |
| Final graded | `0` / statsGraded=None |
| Aborted/hung endpoints | /api/cockpit/stream, /api/daily-pick, /api/dev-radar, /api/judges, /api/learning/stats, /api/letter/brain, /api/letter/daily, /api/letter/weekly, /api/market-drivers, /api/market-drivers/97, /api/message-intel/status, /api/mindmap/graph, /api/mindmap/story-path, /api/mindmap/trail, /api/ops/evidence, /api/portfolio/status, /api/simivision, /api/story-strip, /api/subnet-integrations, /api/subnets, /api/watchlist, /api/whales/flow-signals |
| Aborted hero-critical | /api/learning/stats, /api/daily-pick, /api/daily-pick, /api/learning/stats, /api/daily-pick, /api/daily-pick |
| /health n / ok | 13 / 7 |
| /health p50 / p95 / p100 | 1291.59 / 8038.19 / 8039.51 ms |
| /health p95 over 500ms | True |
| Max concurrent in-flight (all / api) | 47 / 27 |
| Pending API still outstanding at t=45s | /api/cockpit/stream, /api/daily-pick, /api/learning/stats, /api/letter/brain, /api/market-drivers/97, /api/message-intel/status, /api/mindmap/story-path, /api/portfolio/status, /api/story-strip, /api/subnets, /api/watchlist |
| API request count | 43 |
| Homepage curl TTFB (sanity) | 2555.6 ms status=200 |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `True`
