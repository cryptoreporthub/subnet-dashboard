# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-26T17:48:00Z  
**main:** `e926c40` — post-stability sprint **COMPLETE** (#508 Wave E)

## Post-stability sprint (`post-stability-sprint-plan.md`)

| Wave | Status | PRs |
|------|--------|-----|
| A Verify/G0 | ✅ | #501, prod `g0_phone_qa.sh` 2026-07-26 |
| B Batch 0 | ✅ | #486–#488 |
| C Pump parity | ✅ | #489, #493 |
| D Chat | ✅ | #492–#507 |
| E Integrations | ✅ | **#508** (phased; supersedes #449) |

**Prod verified after #508:** `/health` OK · `/api/subnet-integrations/signals` OK · G0 script green.

## Learning loop (`learning-loop-full-integration-plan.md`)

Phases 0–6 merged (#498–#504). Separate track — babysit agent did not own `internal/learning/*`.

## Housekeeping (human)

Close superseded PRs — agent token lacks `closePullRequest`:

- #455, #491, #487, #474, #449

## Out of scope (skipped)

- Chutes billing / live LLM chat replies (human Fly secrets)

## Ops optional

- `APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/verify_prod.sh`
- `fly scale count web=1 worker=1 --app subnet-dashboard`
