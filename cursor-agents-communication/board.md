# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-28T06:50:00Z  
<<<<<<< HEAD
**main:** `41bdf12` — #563 Phase B · #562 Phase A · #561 locks · #560 names · SS-TG #557  
**Plans:** `full-roadmap-master-plan.md` · `post-audit-sprint-plan.md`
=======
**main:** `41bdf12` — sprint plan #559 · audit #555–#557 · SS-TG W0–W3  
**Handoff:** `post-audit-sprint-plan.md` · `ditto-cursor-handoff.md`
>>>>>>> 9a81a0e (Phase H: Track 1 soak review checkpoint doc)

## Full roadmap

<<<<<<< HEAD
| Phase | Status |
|-------|--------|
| **0** Names | DONE (#554, #560) |
| **1** Ditto playbook | **DONE** (human 2026-07-28) |
| **2** Track 1 soak | ACTIVE — review 2026-08-04 / 2026-08-11 |
| **3** SS-TG W1–W3 | **on main** (#557) — human 390px gate pending |
| **4** Accuracy lift | gated post-soak |

## Phase 1 — DONE
=======
| Phase | Status | Lock |
|-------|--------|------|
| **A** Ops quick wins | **in flight** | `ops-quick-wins-lock.md` |
| B Outcome boot polish | queued | `outcome-boot-polish-lock.md` |
| C Worker split v2 | queued | `fly-worker-split-v2-lock.md` |
| D Security housekeeping | queued | |
| E–G SS-TG W4–W6 | queued | `subnet-summers-telegram-lock.md` |
| H Soak review | monitor | `track-1-soak-review-lock.md` |

Babysit: `./scripts/babysit_phase.sh <phase>`
>>>>>>> 9a81a0e (Phase H: Track 1 soak review checkpoint doc)

- Human: pump Ditto fetch disabled · Health Monitor artifact mode · stale memories superseded
- Lock: `ditto-automation-migration-lock.md` (Gate 1 cleared)

## Phase 3 — human gate

- W0 #549 · W1–W3 #557 on prod (HTML markers live)
- **You:** 390px Subnet Summers desk — tap message expand, HC strip, proof band

## Post-audit sprint (parallel track)

| Phase | Status |
|-------|--------|
| A Ops quick wins | DONE #562 |
| B Outcome boot | DONE #563 |
| C–H | see `post-audit-sprint-plan.md` |

<<<<<<< HEAD
## Ops evidence — DONE (#546–#552)
=======
- Lock: `track1-soak-lock.md` — soak day 0 = 2026-07-28; review 2026-08-04 / 2026-08-11
- Phase H checkpoint: `track-1-soak-review-lock.md` (GO/HOLD at day 7 / day 14)

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
>>>>>>> 9a81a0e (Phase H: Track 1 soak review checkpoint doc)

## Active (monitor)

| Track | Gate |
|-------|------|
<<<<<<< HEAD
| Pick audit | 23:45 UTC |
| Health Monitor | Ditto artifact mode |
| Track 1 soak | day 7 / day 14 |
| SS-TG Gate 3 | 390px sign-off |
=======
| Pick audit | 23:45 UTC nightly |
| Wed/Sun Health Monitor | Ditto artifact mode |
| Track 1 soak | day 7 / day 14 sign-off (`track-1-soak-review-lock.md`) |
>>>>>>> 9a81a0e (Phase H: Track 1 soak review checkpoint doc)

## Out of scope

- Chutes billing / live LLM chat replies
