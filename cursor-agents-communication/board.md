# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-29T22:45:00Z  
**main:** `2ee0512` — LA #640 · LB #645 · violet accent #643 · audit honesty #631  
**Plans:** `master-sprint-execution-plan.md` · `launch-lc-ld-plan.md` · `accuracy-pump-pattern-plan.md` · `finish-queue-plan.md`

## Full roadmap

| Phase | Status |
|-------|--------|
| **0** Names | DONE (#554, #560) |
| **1** Ditto playbook | **DONE** (human 2026-07-28) |
| **2** Track 1 soak | ACTIVE — review 2026-08-04 / 2026-08-11 |
| **3** SS-TG W1–W3 | **on main** (#557) — human 390px gate pending |
| **4** Accuracy lift | **Acc-0 NEXT** (ledger gap) — do not wait for soak | `accuracy-pump-pattern-plan.md` |

- Human: pump Ditto fetch disabled · Health Monitor artifact mode · stale memories superseded
- Lock: `ditto-automation-migration-lock.md` (Gate 1 cleared)

## Phase 3 — human gate

- W0 #549 · W1–W3 #557 on prod (HTML markers live)
- **You:** 390px Subnet Summers desk — tap message expand, HC strip, proof band

## Master sprint (LC/LD + Acc + PP)

**Lock:** `master-sprint-execution-plan.md` — merge → babysit → human review between every step

| Step | Phase | Status |
|------|-------|--------|
| M0 | Merge plan PRs #647 + #646 | **NEXT** |
| 1 | Acc-0 ledger plumbing | queued |
| 2 | PP-0 segment ledger | queued |
| 3 | LC legal/trust/SEO | queued |
| 4 | LD surface honesty | queued |
| 5 | Acc-1 archive measure | gated |
| 6 | PP-1 pattern classes | gated |
| 7 | Acc-2 one experiment | gated |
| 8 | PP-2 desk + council | gated |
| 9 | FQ-4 combined angles | gated (`graded>0`) |

Babysit: `./scripts/babysit_phase.sh <phase>` · rollup: `./scripts/babysit_phase.sh sprint`

## Launch readiness (hero + integrations)

| Phase | Status | Lock |
|-------|--------|------|
| **LA** Hero source-of-truth | **DONE** #640 | — |
| **LB** Integrations + pulse rail | **DONE** #645 | — |
| **LC** Legal / trust / SEO | **IN PR** | `launch-lc-ld-plan.md` |
| **LD** Surface honesty | gated on LC | same |

## Accuracy + pump pattern (parallel tracks)

| Phase | Status | Lock |
|-------|--------|------|
| **Acc-0** Ledger plumbing + epoch footgun | **DONE** #649+#650 (in PP-0 PR) | `accuracy-pump-pattern-plan.md` |
| **Acc-1** Archive measurement | gated on Acc-0 | same |
| **Acc-2** One evidence-backed experiment | gated on Acc-1 report | same |
| **PP-0** Segment ledger (waveform) | **IN PR** | same |
| **PP-1** Pattern taxonomy + classifier | gated on PP-0 | same |
| **PP-2** Pump desk + council surfaces | gated on PP-1 | same |

Babysit: `./scripts/babysit_phase.sh acc0` · `acc1` · `pp0` · `pp1` · `pp2`

- Prod epoch reset 2026-07-29: prior 496 graded @ 33.7%; current graded=0; today's LONG has ledger gap until Acc-0

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
