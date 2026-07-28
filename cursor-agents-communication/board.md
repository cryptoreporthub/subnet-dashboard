# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-28T06:30:00Z  
**main:** `3ddc7e9` — #560 SN23 Trishool · #554 Phase 0 names · ops evidence #546–#552  
**Plan:** `full-roadmap-master-plan.md`

## Phase 0 — DONE

- #554 merged + #560 SN16 Fast Thinker, SN23 Trishool overrides
- Lock: `subnet-display-names-lock.md`

## Phase 1 — IN PROGRESS (docs + human Ditto)

- Branch: `cursor/ditto-automation-playbook-4988`
- Lock: `ditto-automation-migration-lock.md`
- **Human:** disable Pump Desk Ditto fetch (`8afd9502…`); Health Monitor artifact mode

## Phase 2 — PARALLEL (monitor doc)

- Lock: `track1-soak-lock.md` — soak day 0 = 2026-07-28; review 2026-08-04 / 2026-08-11

## Ops evidence — DONE

| Piece | PR | Artifact |
|-------|-----|----------|
| Pick audit | #546 | `data/pick_audits/` |
| Pump desk | #547 | `data/pump_desk/latest.json` |
| Outcomes | #550 | `data/learning_outcomes/latest.json` |
| API | #550 | `GET /api/ops/evidence` |

## Learning loop

- Prod: monitor `degraded` when resolver stale — recovers on tick
- Track 1 soak running under #551 calibration

## Active (monitor)

| Track | Gate |
|-------|------|
| Pick audit | 23:45 UTC nightly |
| Wed/Sun Health Monitor | Ditto artifact mode |
| Track 1 soak | day 7 / day 14 sign-off |

## Out of scope

- Chutes billing / live LLM chat replies
