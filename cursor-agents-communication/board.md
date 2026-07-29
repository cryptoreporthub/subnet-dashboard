# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-29T20:40:00Z  
**main:** `c8a1146` — #632 reaction crowns · #638 resolver badge · finish-queue Slices 0–3 · worker hotfixes  
**Plans:** `pre-aug4-polish-plan.md` (**active**) · `finish-queue-plan.md` · `full-roadmap-master-plan.md`

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
| **Finish queue** | Slices 0–3 **DONE** · #629 · #632 crowns · **Pre–Aug 4 wave** → `pre-aug4-polish-plan.md` (PR1–10 then H2 → Slice 7) |
| **Pre–Aug 4 polish** | Plan locked — await **EXECUTE** · PR1 Slice 4 evidence → PR2–10 visuals/UX · Aug 4 H2 gate |

## Prod cache (2026-07-29)

- `subnet_count=128` · `effective_source=blockmachine` · `stale=false` · `boot_status=sync_done ok:true`
- Babysit phase C + learning loop **green**
- Human: H1 390px SS-TG · H2 soak Aug 4 · H3 soak Aug 11 · Telegram session re-bootstrap (`AuthKeyDuplicatedError`)

## Out of scope

- Chutes billing / live LLM chat replies
