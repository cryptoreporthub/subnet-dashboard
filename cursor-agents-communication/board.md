# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-28T09:30:00Z  
**main:** `2ffd728` — post-audit A–H (#562–#571) · Phase C prep #566 · names #554/#560  
**Plans:** `full-roadmap-master-plan.md` · `post-audit-sprint-plan.md`

## Full roadmap

| Phase | Status |
|-------|--------|
| **0** Names | DONE (#554, #560) |
| **1** Ditto playbook | **DONE** (human 2026-07-28) |
| **2** Track 1 soak | ACTIVE — review 2026-08-04 / 2026-08-11 |
| **3** SS-TG W1–W3 | **on main** (#557) — human 390px gate pending |
| **4** Accuracy lift | gated post-soak |

- Human: pump Ditto fetch disabled · Health Monitor artifact mode · stale memories superseded
- Lock: `ditto-automation-migration-lock.md` (Gate 1 cleared)

## Phase 3 — human gate

- W0 #549 · W1–W3 #557 on prod (HTML markers live)
- **You:** 390px Subnet Summers desk — tap message expand, HC strip, proof band

## Post-audit sprint

| Phase | Status | Lock |
|-------|--------|------|
| A Ops quick wins | DONE #562 | `ops-quick-wins-lock.md` |
| B Outcome boot | DONE #563 | `outcome-boot-polish-lock.md` |
| **C Worker split v2** | **PREP #566 · enablement in flight** | `fly-worker-split-v2-lock.md` |
| D Security | DONE #567 | `security-housekeeping-lock.md` |
| E SS-TG W4 | DONE #570 | `subnet-summers-telegram-lock.md` |
| F SS-TG W5 | DONE #571 | |
| G SS-TG W6 | DONE #569 (env-gated) | |
| H Soak review | monitor #568 | `track-1-soak-review-lock.md` |

Babysit: `./scripts/babysit_phase.sh <phase>`

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
| Health Monitor | Ditto artifact mode |
| Track 1 soak | day 7 / day 14 sign-off (`track-1-soak-review-lock.md`) |
| SS-TG Gate 3 | 390px sign-off |
| **SS-TG visual flagship** | P1–P4 in flight — green/blue/orange lead, pink sparse; sitewide color deferred |
| **Phase C enable** | human: `./scripts/fly_enable_worker_v2.sh` after volume on worker |

## Out of scope

- Chutes billing / live LLM chat replies
