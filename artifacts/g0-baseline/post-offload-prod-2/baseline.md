# G0 baseline — `post-offload-prod-2`

Captured: 2026-08-26T21:56:52.052995Z
Base: https://subnet-dashboard.fly.dev
Shape: **SLOW_BUT_COMPLETE**

| Metric | Value |
|--------|-------|
| Hero complete time | NEVER (budget ≤ 10.0s) |
| stats parsed at | None |
| hero DOM ready at | None |
| Final title | `None` |
| Final verdict | `None` |
| Final graded | `None` / statsGraded=None |
| Aborted/hung endpoints | (none) |
| Aborted hero-critical | (none) |
| /health n / ok | 6 / 0 |
| /health p50 / p95 / p100 | 8035.98 / 8050.64 / 8054.55 ms |
| /health p95 over 500ms | True |
| Max concurrent in-flight (all / api) | 1 / 0 |
| Pending API still outstanding at t=45s | (none) |
| API request count | 0 |
| Homepage curl TTFB (sanity) | 20046.5 ms status=None |

Starvation shape (critical abort/hang >45s AND hero misses 10s budget): `False`
