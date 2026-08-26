# G0 baseline — `local-sanity`

Captured: 2026-08-26T18:00:38.731282Z
Base: http://127.0.0.1:50745
Shape: **STARVATION**

| Metric | Value |
|--------|-------|
| Hero complete time | NEVER (budget ≤ 10.0s) |
| stats parsed at | 2.335 |
| hero DOM ready at | None |
| Final title | `Awaiting subnet` |
| Final verdict | `forming` |
| Final graded | `0` / statsGraded=0 |
| Aborted/hung endpoints | /api/cockpit/stream |
| Aborted hero-critical | (none) |
| /health n / ok | 198 / 198 |
| /health p50 / p95 / p100 | 1.14 / 1.39 / 1060.17 ms |
| /health p95 over 500ms | False |
| Max concurrent in-flight (all / api) | 47 / 25 |
| Pending API still outstanding at t=45s | /api/cockpit/stream |
| API request count | 63 |
| Homepage curl TTFB (sanity) | 1.5 ms status=200 |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `True`
