# Phase P — Production snapshot (2026-07-15)

**URL:** https://subnet-dashboard.fly.dev  
**Flags:** `CALIBRATION_AUTO_RETRAIN=on`, `CONVICTION_ALERTS_ENABLED=on`

## P5 backtest (`GET /api/backtest`)

| Metric | Value |
|--------|-------|
| Sample size | 200 |
| Council win-rate | 53.5% |
| Oracle win-rate | 53.5% |
| Oracle PnL (total %) | +32.58 |
| Oracle score ≥0.55 hit-rate | **69.8%** (116 rows) |

Baseline before N/O was ~45.5%. **Lift confirmed** — no N1 council grader reopen.

## Prod endpoints

| Check | Result |
|-------|--------|
| `/health` | OK |
| `/api/calibration/status` → auto_retrain | true, sample 251 |
| `/api/conviction-alerts/status` → enabled | true |

Re-run: `./scripts/verify_prod.sh`
