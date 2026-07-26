# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-26T17:30:00Z  
**main:** `7a5de5a` · Learning loop Phases 0–6 merged

## Active plan

**Canonical:** `cursor-agents-communication/learning-loop-full-integration-plan.md`  
**Status:** **DONE** (Phases 0–6 on `main`)

| Phase | PR | Status |
|-------|-----|--------|
| 0 Instrumentation | #498 | ✅ |
| 1 Schedulers | #500 | ✅ |
| 2 Score snapshots | #502 | ✅ |
| 3 Shadows / HOLD | #503 | ✅ |
| 4–6 bridges + trust + verify | #504 | ✅ |

## Ops follow-up

- Confirm worker/essential process writes `score_snapshots.json` (snapshot_age non-null)
- `APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/verify_prod.sh`
- Optional: `fly scale count web=1 worker=1`

## Prior (done)

Pump-site + G0 · H1 SSE · Calibration (#494).
