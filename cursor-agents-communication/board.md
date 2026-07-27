# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-27T01:25:00Z  
**main:** learning-loop audit hardening in PR  
**prod baseline (2026-07-27):** `/health` OK · `/api/learning/health` `status=ok` · `worker_peer.alive=true` · `resolver.running=true` · HOLD daily (28% &lt; 40% gate) · `snapshot_age_seconds` null (first score-snapshot cycle pending)

## Learning loop audit (2026-07-27)

- Live prod verified via `check_learning_loop.sh` (ok; snapshot not written yet post-boot).
- Hardening PR: CI learning-loop tests, deploy `check_learning_loop.sh`, heavy-job mutex, softer warm/verify scripts, resolver web guard, plan doc cleanup.
- **Fly secrets:** agent env lacked `FLY_API_TOKEN`; confirm `WORKER_HEAVY=essential` via `flyctl secrets list` (human or env with token).

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

Phases 0–6 merged (#498–#504). **#519:** cross-process health (`resolver.running` from worker heartbeat), inline worker supervisor, score snapshot soul_map.

**Prod 2026-07-26:** `verify_prod.sh` OK · worker alive · resolver `running: true` · may show `stalled` until resolver tick clears 1 young pending · `snapshot_age` fills after first score-snapshot job.

**Human ops (agent cannot):**
- Close superseded PRs: #455, #491, #487, #474, #449
- `WORKER_HEAVY=full` wedged 2GB single VM (#517→#520 revert) — Telegram needs split VM or lighter path

## Housekeeping (human)

Close superseded PRs — agent token lacks `closePullRequest`:

- #455, #491, #487, #474, #449

## Out of scope (skipped)

- Chutes billing / live LLM chat replies (human Fly secrets)

## Ops optional

- `APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/verify_prod.sh`
- `fly scale count web=1 worker=1 --app subnet-dashboard`
