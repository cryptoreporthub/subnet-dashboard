# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-28T05:00:00Z  
**main:** `31e84b1` — **#554 Phase 0** subnet names · #557 SS-TG W1 flags · ops evidence #546–#552  
**Handoff:** `full-roadmap-master-plan.md` · `ditto-cursor-handoff.md`

## Phase 0 — DONE (#554)

- Merged + deployed (Fly deploy OK; post-check failed resolver stale — app live)
- SN16 → **Fast Thinker** override live (`/api/subnets` verified)
- Lock: `subnet-display-names-lock.md`

**Review Gate 0 (human tick):**
- [x] PR merged + deploy shipped code
- [ ] Pump desk homepage + `/pump` names spot-check @390px
- [ ] Council pick / weighed room no regression
- [x] `/api/subnets` TMC feed + Fast Thinker SN16
- [ ] Ditto: supersede Jul 27 pump-automation WARN memories

## Ops evidence loop — DONE

| Piece | PR | Artifact |
|-------|-----|----------|
| Pick audit | **#546** | `data/pick_audits/` |
| Pump desk snapshot | **#547** | `data/pump_desk/latest.json` |
| Outcome snapshot | **#550** | `data/learning_outcomes/latest.json` |
| Ops evidence API | **#550** | `GET /api/ops/evidence` |
| Calibration | **#551** | rebase #491 |

## Learning loop

- Prod: may show `degraded` when resolver tick stale post-deploy — recovers on tick
- LONG SN16 · worker alive

## Next — Phase 1 (after Gate 0 tick)

Ditto automation migration playbook — disable pump fetch automation; Health Monitor artifact mode. See `full-roadmap-master-plan.md` Phase 1.

## Active (monitor)

| Track | Gate |
|-------|------|
| Track 1 soak | 7–14d (#543 + #551) |
| Pick audit | 23:45 UTC nightly |
| Wed Health Monitor | artifact mode |

## Out of scope

- Chutes billing / live LLM chat replies
