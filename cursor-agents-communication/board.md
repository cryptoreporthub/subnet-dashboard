# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-26T19:20:00Z  
**main:** `7357bc9` — #518 + #519 merged; **#520** hotfix `WORKER_HEAVY=essential` (full wedged prod)

## Post-stability sprint (`post-stability-sprint-plan.md`)

| Wave | Status | PRs |
|------|--------|-----|
| A Verify/G0 | ✅ | #501, prod `g0_phone_qa.sh` 2026-07-26 |
| B Batch 0 | ✅ | #486–#488 |
| C Pump parity | ✅ | #489, #493 |
| D Chat | ✅ | #492–#507 |
| E Integrations | ✅ | **#508** (phased; supersedes #449) |

**Prod verified:** `/health` OK · G0 green · `/api/subnet-integrations/signals` OK · `verify_prod.sh` hardened (readiness timeout → WARN, not abort).

## Telegram intel + outcome loop (#513–#515 on `main`)

Message-intel rollup UI, listener hardening, background price-outcome loop (`outcomes` in `/api/message-intel/status`). Babysit: prod verify + `verify_prod.sh` coverage.

## Learning loop (`learning-loop-full-integration-plan.md`)

Phases 0–6 merged (#498–#504). **Babysit PR:** cross-process `/api/learning/health`, inline worker supervisor, score snapshot soul_map cycle.

**Human ops (agent cannot flyctl):**
- Close superseded PRs: #455, #491, #487, #474, #449
- Telegram + outcomes live: `WORKER_HEAVY=full` wedges single 2GB VM — use `essential` + manual soak; see `DEPLOY.md`

## Housekeeping (human)

Close superseded PRs — agent token lacks `closePullRequest`:

- #455, #491, #487, #474, #449

## Out of scope (skipped)

- Chutes billing / live LLM chat replies (human Fly secrets)

## Ops optional

- `APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/verify_prod.sh`
- `fly scale count web=1 worker=1 --app subnet-dashboard`
