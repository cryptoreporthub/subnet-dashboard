# STATUS

**Updated:** 2026-07-17T22:10:00Z  
**active plan:** `s33-prod-readiness-plan.md` — **§33 complete**  
**main:** `e25ed13` (hotfix PR pending)

## Done

- §33 ops: `/api/ops/readiness`, feed warmup, subnet load timeout, DEPLOY troubleshooting
- §32 trust product merged (#320)
- §31 website opt merged (#319)
- Prod post-deploy: TMC 129 subnets, TaoStats configured, resolver running, graded 453 on volume

## Hotfix

- Readiness `graded` used wrong engine field → trust_banner
- `/api/subnets` re-enriched with `use_taostats=True` per row → 35s+ timeout on Fly

## Skipped

- H1 custom domain
