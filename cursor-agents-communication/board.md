# Subnet Dashboard Coordination Board

**Last updated:** 2026-08-02T11:52:00Z  
**main:** `4cbfe94` (#765 soul_map deepcopy) · **infra:** v1 stable; GIL unwedge #755–#763 · timeouts #734–#737 #751–#754  
**Active plan:** `post-hero-finish-plan.md` (Steps 0–6 done; Step 5 human glance **after layout**; Step 7 soak gated Aug 4 / Aug 11)  
**Models:** `model-guide.md` — Grok LOCK/review; Composer implements; Sonnet low reviews  
**Plans:** `post-hero-finish-plan.md` · `accuracy-lift-lock.md` · `hero-mindmap-sprint-plan.md` (#723) · `completion-runbook.md`

## STATUS SNAPSHOT (2026-08-02)

| Item | Status |
|------|--------|
| Phase 1–2 soul_map I/O + read cache | **MERGED** #718 · #719 |
| Phase A/B Judges + Telegram Pulse loops | **MERGED** #720 · #721 |
| Phase C mindmap display wiring | **MERGED** #741 (+ M1–M5 #725–#735) |
| Hero H1/H2 + A-tier ACs | **MERGED** #724 · #727 · #732 · #736 |
| Mindmap graph wedge (full state on graph) | **MERGED** #744 — graph skips `build_mindmap_state` |
| API unwedge (subnets/judges/simivision/cockpit) | **MERGED** #743 · #759–#761 |
| API timeout wrappers + mindmap bounds | **MERGED** #734 · #737 · #751 · #753 · #754 |
| Finish queue Steps 1–6 | **MERGED** #745–#752 · #755–#763 (summary/health GIL unwedge) |
| Mindmap summary / learning health | **PASS** — summary ~0.5s file-only; health cache+peer; Fly green |
| Agent babysit + g0 (2026-08-02) | **PASS** — `babysit_phase.sh sprint` + `g0_phone_qa.sh` EXIT 0; mindmap non-5xx (slow 12–17s under load OK) |
| Human 390px glance (AC7) | **PENDING** — human doing layout change; sign off after — `hero-mindmap-390-signoff-2026-08-02.md` |
| Accuracy PREP (read-only evidence) | **MERGED** #740 — experiments **GATED** Aug 4 H2 soak GO |
| Stale drafts (#686/#675/#692/#650) | **Do not blind-merge** — superseded / already on main |

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
| **2** Track 1 soak | ACTIVE — review **2026-08-04** / 2026-08-11 (`track1-soak-lock.md`) |
| **3** SS-TG W1–W3 | **on main** (#557) — H1 **cleared** |
| **4** Accuracy lift | Acc-0–2 **DONE**; PREP #740 on main; Slice 7b/7c + Combined tune **after H2 GO** | `accuracy-lift-lock.md` |

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

## Prod cache (2026-08-02 post-#765)

- Babysit sprint + g0 phone QA **green** (agent run ~11:35 UTC; g0 re-run ~11:51 UTC)
- Mindmap graph/trail/state/story-path: **non-5xx**; latency 0.5–17s depending on cache warmth (timeouts serve degraded/cached JSON)
- `daily-pick` HOLD · `pump-alerts` success · `ops/live` worker alive
- Human: **390px sign-off after layout** · H2 soak Aug 4 · H3 soak Aug 11

## Out of scope

- Chutes billing / live LLM chat replies
