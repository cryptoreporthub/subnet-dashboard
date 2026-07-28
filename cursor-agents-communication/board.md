# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-28T01:30:00Z  
**main:** `659e416` — #551 calibration · #550 outcome harness · #547 regen+pump · #546 audit  
**Handoff:** `ops-evidence-master-plan.md` · `ditto-cursor-handoff.md`

## Ops evidence loop — DONE (S1–S3)

| Piece | PR | Artifact |
|-------|-----|----------|
| Pick selection audit | **#546** | `data/pick_audits/` |
| Pump desk snapshot | **#547** | `data/pump_desk/latest.json` |
| Outcome snapshot | **#550** | `data/learning_outcomes/latest.json` |
| Ops evidence API | **#550** | `GET /api/ops/evidence` |
| GHA probe | **#550** | `ops-evidence.yml` |
| Calibration hardening | **#551** | rebase #491 |

Locks: `pick-audit-lock.md` · `outcome-snapshot-lock.md`

## Learning loop

- Prod: `status ok` · LONG SN16 (2026-07-28) · worker alive
- Council health: WATCH ~67 / 33% accuracy (expected soak)

## Ditto automations

| Job | Action |
|-----|--------|
| Pump Desk Intelligence Snapshot | **DISABLE** (worker owns) |
| Council Health Monitor | Read `learning_outcomes/latest.json` — see `docs/ditto-council-health-artifacts.md` |
| Daily Brief / Weekly Learning | KEEP |

## Active (monitor)

| Track | Gate |
|-------|------|
| Track 1 soak | 7–14d publish rate (#543 + #551) |
| Wed Health Monitor | Auto run + artifact mode |
| Pick audit | 23:45 UTC nightly PASS/MISS |
| **#552** polish | Boot outcome tick + stale alert guard |

## Out of scope

- Chutes billing / live LLM chat replies
