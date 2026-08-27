# Subnet Dashboard Coordination Board

**Last updated:** 2026-08-27T06:30:00Z  
**main:** `688f0aef` — freshness policy contracts (#1058 P1 hydration, REV3 audit, resolver revive #1050–#1051, shadow expire #1055)  
**Models:** `model-guide.md` — **Composer 2.5** builds · **Grok 4.6 medium** design/root-cause LOCK · **Luna high** AC/honesty final pass (no Sonnet 4.5/4.6)  
**Active plans:** `grok-dispatch-prompts-2026-08-27.md` · `g0-1058-composer-p1-handoff.md` · `accuracy-lift-lock.md` · `gameplan-beyond-16.md` (§17 **COMPLETE**)

## STATUS SNAPSHOT (2026-08-27)

| Item | Status |
|------|--------|
| **§17 beyond trust gap** | **COMPLETE** on main — S/U/F slices shipped (bands, magnitude, badge, home, watchlist, alerts, portfolio, letter, chat, message-intel) |
| **#1058 hydration starvation** | **P1 MERGED** `64176d16` — SSR pick read-only + bounded `GET /api/daily-pick` · **issue OPEN** — post-P1 prod audit **FAIL** (hero >10s, `/health` p95 ~8s during burst) |
| **#1058 Phase 2** | **GATED on Grok LOCK** — client stagger in `cockpit_hydrate.js` · prompts: `grok-dispatch-prompts-2026-08-27.md` (Grok A) |
| **G0 harness** | **PASS** reproduced starvation (`artifacts/g0-baseline/G0_REPORT.md`) · post-P1 reprobe **FAIL** close bar |
| **REV3 closeout** | **PARTIAL** — audit **MERGED** #1053/#1054 · Site C PASS · **Site A: Sentinel PASS** (no code) — stale audit on pre-#1055 SHA; close after deploy ≥ `b586afc` + 1 `resolve_due` tick · Site B cosmetic `pending_count` only |
| **Resolver / grading wave** | **MERGED** #1050 (degraded payloads + grading A–B) · #1051 (revive hung scheduler + honest running health) |
| **Shadow expire (#1055)** | **MERGED** `b586afc` — past-grace shadows expire; excluded from watchdog warning · `dd13cfb298` explainable HOLD shadow; row retires on tick post-deploy |
| **Loop honesty (#1056/#1057)** | **MERGED** — `loop_learned.weight_updates` truthful |
| **Freshness contracts** | **MERGED** `688f0aef` — source-specific freshness + human approval policy |
| **Intel loop v2.1 (#1034)** | **DRAFT OPEN** — `docs/intel-loop-v21-review-findings.md` · 62 focused tests pass · merge readiness = Grok honesty review (queued) |
| **Accuracy lift experiments** | **GATED** — PREP on main; Slice 7b/7c after soak GO + `graded_30d ≥ 20` (`accuracy-lift-lock.md`) |
| **Opus tribunal #788** | **PARKED** — superseded by Council Hero v4 handoff; no live wire without explicit human ask |
| **Phase L signals (B)** | Slice 1 done · L2–L4 **await Grok LOCK** for WebSocket + rules engine (`model-guide.md` §4) |
| **Agent mode** | **One Cloud Agent + subagents** — Agent A (`-843d`) **retired** |
| Stale drafts (#686/#675/#692/#650) | **Do not blind-merge** |

## Agent dispatch (now)

| Run | Model | Task | Lock / prompt |
|-----|-------|------|----------------|
| **Drift/QA** | Grok medium | #1058 Phase 2 hydrate stagger LOCK | `grok-dispatch-prompts-2026-08-27.md` |
| **Composer** | 2.5 slow | Implement after Drift/QA LOCK lands | `cursor/hydrate-stagger-phase2-*` |
| **Luna** | high | Final AC pass on #1058 Phase 2 PR | mandatory — do not skip |

## Infra STATUS

| Item | Status |
|------|--------|
| **Runtime** | Fly v1 inline worker (`WORKER_SPLIT_V2=off`) · shared-cpu web+worker on one machine |
| **v2 rollback** | split_v2 web→worker private HTTP unreachable — **do not re-enable** without soak + human approve |
| **Mindmap event-loop wedge (#710)** | **FIXED** — dropped sync TaoStats fallback on hot read paths |
| **Hydration occupancy (#1058)** | **ACTIVE** — 27–28 concurrent `/api/*` at DCL starves event loop; P1 cut sequential 8s daily-pick wait; Phase 2 JS stagger next |
| **Deploy** | Human-gated `workflow_dispatch` for Fly · no agent deploy without owner GO |
| **Sentry** | Stages B/C/D on main; release from Git SHA; TaoStats noise scrub |

## Full roadmap

| Phase | Status |
|-------|--------|
| **0** Names | DONE |
| **1** Ditto playbook | DONE |
| **2** Track 1 soak | H2/H3 dates passed — use `soak_review_snapshot.sh` + `accuracy_lift` block for ongoing monitor |
| **3** SS-TG W1–W3 | on main |
| **4** Accuracy lift | Acc-0–2 DONE; PREP merged; **7b/7c GATED** |
| **§17** | **COMPLETE** |
| **§18+** | Monitor / queued (see `s18-automated-build-plan.md`, `s19`–`s27` hygiene plans) |

## Master sprint (LC/LD + Acc + PP)

**DONE** — M0 through FQ-4 (#647–#670). Babysit: `./scripts/babysit_phase.sh sprint`

## Launch readiness (hero + integrations)

| Phase | Status |
|-------|--------|
| LA–LD | **DONE** |
| §16 trust gap | **DONE** |
| §17 product waves | **DONE** |

## Ops evidence

| Piece | Artifact |
|-------|----------|
| Pick audit | `data/pick_audits/` nightly 23:45 UTC |
| Pump desk | `data/pump_desk/latest.json` |
| Outcomes | `data/learning_outcomes/latest.json` |
| API | `GET /api/ops/evidence` (+ `accuracy_lift` PREP block) |
| G0 hydration | `harness/g0_hydration_starvation/` + `artifacts/g0-baseline/` |

## Learning loop

- Prod: `/api/learning/health` expected ok when worker volume alive
- Resolver scheduler revive **MERGED** #1051
- Shadow/counterfactual expire **MERGED** #1055 — verify Site A close on prod
- Track 1 calibration #551 — ongoing monitor, not blocking Phase 2 hydrate

## Active (monitor)

| Track | Gate |
|-------|------|
| **#1058 Phase 2** | Drift/QA LOCK → Composer → Luna → owner deploy → G0 ×2 on prod |
| **REV3 Site A** | Sentinel PASS — owner deploy SHA ≥ `b586afc` + 1 `resolve_due` tick; no volume edit |
| **Intel #1034** | Grok honesty review → merge when green |
| **Accuracy lift 7b/7c** | `graded_30d ≥ 20` + human GO |
| **Phase L3/L4** | Grok design LOCK before Composer build |
| **Opus tribunal #788** | PARKED |
| **Pick audit / Health Monitor** | Ditto artifact mode |
| **Human 390px glance** | PENDING when hero path stable post-#1058 |

## Prod notes (2026-08-27)

- Sequential `GET /api/daily-pick` improved post-P1 (~0.75s stored HOLD vs G0 8.3s timeout HOLD)
- Browser cold load still starves: stats aborted at 28s retry budget; `/health` p95 ~8s during fan-out
- Pump desk automation (Ditto 2026-08-25): no BUILDING alerts; daily-pick may HOLD when handler busy
- REV3 Site A: Sentinel PASS 2026-08-27 — `dd13cfb298` was audited on pre-#1055 SHA; live watchdog already clean (`oldest` ≠ `dd13cfb298`)
- **Next:** Drift/QA LOCK for #1058 Phase 2; owner REV3 closeout deploy if prod still on `35b1bf34`

## Out of scope

- Chutes billing / live LLM chat replies
- `fly.toml` / VM resize without human approve
- split_v2 re-enable without proven soak
