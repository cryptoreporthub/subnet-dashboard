# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-29T15:10:00Z  
**main:** `0ba03c0` — #630 TaoStats web wedge · #632 SS-TG reaction crowns · #631 audit honesty · #629 live_subnets sync lock · finish-queue Slices 0–3 (#609–#610, worker hotfix #619–#626)  
**Plans:** `finish-queue-plan.md` · `full-roadmap-master-plan.md` · `post-audit-sprint-plan.md` · `launch-lc-ld-plan.md`

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

## Launch readiness (hero + integrations)

| Phase | Status | Lock |
|-------|--------|------|
| **LA** Hero source-of-truth | **DONE** #640 | — |
| **LB** Integrations + pulse rail | **DONE** #645 | — |
| **LC** Legal / trust / SEO | **NEXT** | `launch-lc-ld-plan.md` |
| **LD** Surface honesty | gated on LC | same |

Babysit: `./scripts/babysit_phase.sh la` · `lb` · `lc` · `ld`

## Post-audit sprint

| Phase | Status | Lock |
|-------|--------|------|
| A Ops quick wins | DONE #562 | `ops-quick-wins-lock.md` |
| B Outcome boot | DONE #563 | `outcome-boot-polish-lock.md` |
| **C Worker split v2** | **DONE** (#598–#601 · peer alive · GHA green) | `fly-worker-split-v2-lock.md` |
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

- Prod: `/api/learning/health` **ok** — resolver tick live on worker volume (proxy from web)
- Readiness `learning_loop_health` fix **DONE** (#602) — orphan web `soul_map` no longer disables proxy
- Track 1 soak running under #551 calibration

## Active (monitor)

| Track | Gate |
|-------|------|
| Pick audit | 23:45 UTC nightly |
| Health Monitor | Ditto artifact mode |
| Track 1 soak | day 7 / day 14 sign-off (`track-1-soak-review-lock.md`) |
| SS-TG Gate 3 | 390px sign-off (H1) |
| **SS-TG visual flagship** | DONE #590 + #605 stale feed backfill · #596 sitewide palette |
| **Phase C** | **DONE** — `worker_peer.alive: true` · worker HTTP `:8081` · flycast `:8081` |
| **Finish queue** | Slices 0–3 **DONE** · #629 sync lock + deploy poll · #630 TaoStats wedge **DONE** · Slice 4 **HOLD** (graded=0, calls=12) · Slices 5–7 gated (`finish-queue-plan.md`) |

## Prod cache (2026-07-29 post-#630)

- `subnet_count=128` · `effective_source=blockmachine` · `stale=false` · `rpc_healthy=true`
- Babysit phase C + learning loop **green** (verified after #630 deploy)
- Human: H1 390px SS-TG · H2 soak Aug 4 · H3 soak Aug 11 · Telegram session re-bootstrap if `AuthKeyDuplicatedError` recurs

## Out of scope

- Chutes billing / live LLM chat replies
