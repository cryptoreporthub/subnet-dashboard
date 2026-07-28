# Outcome snapshot lock (learning loop evidence)

**Status:** ACTIVE  
**Branch:** `cursor/outcome-snapshot-harness-4988`  
**Plan:** `ops-evidence-master-plan.md`

## Goal

Daily + periodic **outcome quality** artifact — directional accuracy, council health score, expert weights — without re-scoring picks.

**Not** selection audit (#546) — that is `data/pick_audits/`.

## Harness

| Piece | Location |
|-------|----------|
| Core | `internal/learning/outcome_snapshot.py` |
| Health score | `internal/learning/council_health_score.py` |
| Scheduler | `internal/learning/outcome_snapshot_scheduler.py` |
| Ops bundle | `internal/ops/evidence.py` → `GET /api/ops/evidence` |
| Artifact | `data/learning_outcomes/latest.json` |
| Manual | `scripts/learning_outcome_snapshot.sh` |

**Schedule:** 04:50 UTC daily + every 6h (`OUTCOME_SNAPSHOT_INTERVAL_HOURS`)

## Ditto Council Health Monitor

Read `data/learning_outcomes/latest.json` instead of live `/api/council` + `/api/learning/stats` + `/api/subnets` storm.

Fields: `council_health.health_score`, `escalation`, `resolver_stats`, `expert_weights`.

## AC

- [ ] `pytest tests/test_outcome_snapshot.py` green
- [ ] `GET /api/ops/evidence` in contract
- [ ] Worker starts `learning-outcome-snapshot` job
- [ ] GHA `ops-evidence.yml` on main
- [ ] Ditto disables Pump Desk fetch automation

## NON-GOALS

- LLM outcome grading chat
- Replacing resolver or judge postmortems
