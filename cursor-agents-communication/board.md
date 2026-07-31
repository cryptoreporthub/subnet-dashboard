# Subnet Dashboard Coordination Board

**Last updated:** 2026-07-31T17:38:00Z  
**main:** see GitHub · **infra:** v1 canon confirmed stable — real wedge root-caused + fixed (PR #710)  
**Plans:** `completion-runbook.md` · `split-v2-rollback-runbook.md` · `fly-worker-split-v2-lock.md`

## Infra STATUS (launch blocker)

| Item | Status |
|------|--------|
| **Root cause (v2 rollback)** | split_v2 web→worker private HTTP unreachable; volume APIs soft-degraded for weeks |
| **Rollback fix** | Stop forcing `fly.worker-v2.toml` / `FORCE_WORKER_SPLIT_V2` in Fly Deploy; auto-rollback to `fly.toml` + inline worker |
| **Bandaids** | Soft stubs / local fallthrough (#698–#705) — keep as defense only; do not treat as product fix |
| **Do not** | Re-enable v2 without proven peer probe soak + human approve |
| **Post-rollback wedge (AUDIT_HANDOFF #709)** | Root-caused live via `py-spy dump` on prod: `GET /api/mindmap/graph` walked the full pump ladder and re-resolved every subnet name with `use_taostats_fallback=True` — TaoStats is rate-limited to 5 calls/min and `_rate_limit()` sleeps synchronously, blocking the single asyncio event-loop thread (incl. `/health`) for minutes → Fly marks the machine unhealthy → 503 whole site. This was the "data isn't hydrating / empty spaces" bug. |
| **Wedge fix** | PR #710 — dropped `use_taostats_fallback=True` from the 3 hot read paths (`internal/pump/state.py::_normalize_ladder_subnet`, `internal/pump/signals.py::_signal_display_name`, `internal/learning/pump_alert.py::_resolve_name`); names are already resolved once in the background by `transition_subnet`. Added negative-result caching in `internal/subnet_names.py`. This answers `AUDIT_HANDOFF.md` Option C ("fix v1 properly... never block event loop on mindmap/homepage") — **no worker-split/Fly topology change needed**, it was a code bug. |

## Full roadmap

| Phase | Status |
|-------|--------|
| **0** Names | DONE (#554, #560) |
| **1** Ditto playbook | **DONE** (human 2026-07-28) |
| **2** Track 1 soak | ACTIVE — review 2026-08-04 / 2026-08-11 |
| **3** SS-TG W1–W3 | **on main** (#557) — H1 **cleared** (agent wave PR2/PR5) |
| **4** Accuracy lift | **Acc-0 NEXT** (ledger gap) — do not wait for soak | `accuracy-pump-pattern-plan.md` |

- Human: pump Ditto fetch disabled · Health Monitor artifact mode · stale memories superseded
- Lock: `ditto-automation-migration-lock.md` (Gate 1 cleared)

## Phase 3 — human gate

- W0 #549 · W1–W3 #557 on prod (HTML markers live)
- **H1:** cleared 2026-07-30 — agent SS-TG 390px + V5 polish in flight (`pre-aug4-polish-plan.md`)

## Master sprint (LC/LD + Acc + PP)

**Lock:** `master-sprint-execution-plan.md` — merge → babysit → human review between every step

| Step | Phase | Status |
|------|-------|--------|
| M0 | Merge plan PRs | **DONE** #647 |
| 1 | Acc-0 ledger plumbing | **DONE** #649+#651 |
| 2 | PP-0 segment ledger | **DONE** #651+#653 |
| 3 | LC legal/trust/SEO | **DONE** #652 |
| 4 | LD surface honesty | **DONE** #654 |
| 5 | Acc-1 archive measure | **DONE** #655 |
| 6 | PP-1 pattern classes | **DONE** #656 |
| 7 | Acc-2 experiment (A+D blend) | **DONE** #659 |
| 8 | PP-2 desk + council | **DONE** #661 |
| 9 | FQ-4 combined angles | **DONE** #664+#665 — artifact + ops/evidence (strict babysit gated `graded>0`) |

Babysit: `./scripts/babysit_phase.sh <phase>` · rollup: `./scripts/babysit_phase.sh sprint`

## Launch readiness (hero + integrations)

| Phase | Status | Lock |
|-------|--------|------|
| **LA** Hero source-of-truth | **DONE** #640 | — |
| **LB** Integrations + pulse rail | **DONE** #645 | — |
| **LC** Legal / trust / SEO | **DONE** #652 | — |
| **LD** Surface honesty | **DONE** #654 | — |

## Accuracy + pump pattern (parallel tracks)

| Phase | Status | Lock |
|-------|--------|------|
| **Acc-0** Ledger plumbing + epoch footgun | **DONE** #649+#650 (in PP-0 PR) | `accuracy-pump-pattern-plan.md` |
| **Acc-1** Archive measurement | **DONE** #655 | `accuracy-pump-pattern-plan.md` |
| **Acc-2** Horizon 24h + gate 50% | **DONE** #659 | same |
| **PP-0** Segment ledger (waveform) | **DONE** #651+#653 | same |
| **PP-1** Pattern taxonomy + classifier | **DONE** #656 | same |
| **PP-2** Pump desk + council surfaces | **DONE** #661 | same |

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
| SS-TG Gate 3 | H1 cleared — polish wave active |
| **SS-TG visual flagship** | DONE #590 + #605 stale feed backfill · #596 sitewide palette |
| **Phase C** | **DONE** — `worker_peer.alive: true` · worker HTTP `:8081` · flycast `:8081` |
| **Finish queue** | Slice 4 **DONE** #664 · **PR3 NEXT** (listener) · PR4–10 queue (`completion-runbook.md`) · Slice 7 gated Aug 4 |

## Prod cache (2026-07-29 post-#630)

- `subnet_count=128` · `effective_source=blockmachine` · `stale=false` · `rpc_healthy=true`
- Babysit phase C + learning loop **green** (verified after #630 deploy)
- Human: H1 390px SS-TG · H2 soak Aug 4 · H3 soak Aug 11 · Telegram session re-bootstrap if `AuthKeyDuplicatedError` recurs

## Out of scope

- Chutes billing / live LLM chat replies
