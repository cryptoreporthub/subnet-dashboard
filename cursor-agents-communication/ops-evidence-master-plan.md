# Ops evidence master plan (2026-07-28)

**Goal:** Close selection + outcome evidence loops; Ditto reads artifacts; GHA pages on alert.

## Stages

| Stage | Deliverable | Verify | Status |
|-------|-------------|--------|--------|
| S0 | Baseline prod curl | `/api/learning/health` ok | ✅ |
| S1 | Outcome snapshot worker + `/api/ops/evidence` | pytest + contract + deploy | 🔄 |
| S2 | GHA `ops-evidence.yml` | workflow green on main | 🔄 |
| S3 | Ditto Council Health reads `data/learning_outcomes/latest.json` | Wed Health Monitor | Ditto |
| S4 | Calibration hardening (#491 rebase) | publish_gate tests | queued |
| S5 | Track 1 soak (7–14d) | publish rate review | monitor |

## Artifact paths (Fly volume)

| Path | Producer | Consumer |
|------|----------|----------|
| `data/pick_audits/YYYY-MM-DD.json` | pick audit 23:45 UTC | Cursor MISS investigator |
| `data/pump_desk/latest.json` | worker 15m | Ditto optional memory |
| `data/learning_outcomes/latest.json` | worker 04:50 + 6h | Ditto Health Monitor |
| `GET /api/ops/evidence` | on-demand bundle | GHA + humans |

## Ditto automations (do not merge into one)

| Automation | Action |
|------------|--------|
| Pump Desk Intelligence Snapshot | **DISABLE** (worker owns) |
| Daily Council Brief | KEEP |
| Weekly Council Learning | KEEP |
| Council Health Monitor | KEEP — read `learning_outcomes/latest.json` |

## Exit codes

| Script | Exit 2 when |
|--------|-------------|
| `scripts/nightly_pick_audit.sh` | pick audit MISS |
| `scripts/pump_desk_snapshot.sh` | pump alert |
| `scripts/learning_outcome_snapshot.sh` | outcome alert |
| `scripts/check_ops_evidence.sh` | `/api/ops/evidence` status=alert |

Lock: `outcome-snapshot-lock.md`
