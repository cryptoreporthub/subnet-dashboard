# STATUS

**Updated:** 2026-07-18T00:38:00Z  
**main:** `4ab6b2e`  
**active plan:** none — §34 + subnet-names plan **complete** (#325 merged)

## Next (pick one)

1. **E1 test debt** — `post-s28-backlog.md` (judges/phase2/phase_h_ui pre-existing failures)
2. **H1 custom domain** — human DNS + Fly cert (`DEPLOY.md`)
3. **Prod door check** — land on `/` and confirm §34 success metric (call/HOLD + why + evidence)

## Done

- #325 — §34 front-door + subnet-names plan gaps (merged with #324)
- §33 prod readiness — `verify_prod.sh` green on graded/feed/resolver
- §32 trust product · §31 website opt

## Prod verify (2026-07-18)

```
ready: true | graded: 453 | likely_total: 129 | resolver: on
issues: live_subnets_cache_empty, daily_pick_hold_no_published_long
sample_name: Root (no SNNone)
```

## Skipped

- H1 custom domain until human · D1–D7 deferred
