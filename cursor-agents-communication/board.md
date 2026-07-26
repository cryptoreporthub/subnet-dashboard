# Subnet Dashboard Coordination Board

<<<<<<< HEAD
=======
<<<<<<< HEAD
<<<<<<< HEAD
<<<<<<< HEAD
**Last updated:** 2026-07-26T16:55:00Z  
**main:** `083f456` · G0 prod green · cockpit SSE fast path (#497)
=======
**Last updated:** 2026-07-26T16:50:00Z  
**main:** see git (`#494` calibration + follow-ups)
>>>>>>> 20db888 (feat(learning): Phase 0 loop health + ledger contract guard)
=======
>>>>>>> cursor/wave-e-signals-macro-4988
**Last updated:** 2026-07-26T17:30:00Z  
**main:** `7a5de5a` · Learning loop Phases 0–6 merged

## Active plan

**Canonical:** `cursor-agents-communication/learning-loop-full-integration-plan.md`  
<<<<<<< HEAD
**Status:** **DONE** (Phases 0–6 on `main`)
=======
<<<<<<< HEAD
**Status:** Phase **0** done (PR #498) — awaiting merge
=======
**Last updated:** 2026-07-26T17:10:00Z  
**main:** `c0d991f` · post-stability Wave E in PR #508

## Active plan

**Canonical:** `cursor-agents-communication/post-stability-sprint-plan.md`  
**Parallel:** `learning-loop-full-integration-plan.md` — Agent learning-loop (#498–#504); do not collide on `internal/learning/*`
>>>>>>> 3cc35e6 (docs: board Wave E phased + G0 prod pass)

| Wave | Status | Notes |
|------|--------|-------|
| 0 G0 | ✅ | `g0_phone_qa.sh` prod PASS 2026-07-26 (pump API timeout WARN; desk SSR OK) |
| B Batch 0 | ✅ | #486–#488 |
| C P5/C2 | ✅ | #489, #493 |
| D Chat | ✅ | #492–#507 |
| E Integrations | 🔄 | #508 phased signals + macro (supersedes #449 monolith) |

## Next slice queue

<<<<<<< HEAD
1. ~~Slice A–B~~ — attribution + pump desk (#414–#418)
2. ~~Slice R~~ — historical weight rebalance (#419)
3. ~~Slice M~~ — α pump overlay (#419)
4. ~~Full plan Waves 1–3~~ — #410 + follow-ups (#430–#446)
5. ~~G0 human~~ — prod + local 390px pass 2026-07-26
6. **Ops** — `fly scale count worker=1` when ready (#437 worker process)
7. Wave 4 — YAGNI
=======
| Phase | Status | Notes |
|-------|--------|-------|
| 0 Instrumentation | ✅ | `/api/learning/health` + ledger contract (#498) |
| 1 Schedulers | — | gated on 0 merge |
| 2 Score snapshots | — | gated on 1; never score 127 on request |
| 3 Shadows / HOLD / Option A | — | gated on 2 stable |
| 4 Intel / pump / history | — | gated on 3 |
| 5 UI trust | — | gated on 4 |
| 6 Validation | — | gated on 5 |
=======
**Status:** Phases 0–6 implemented on stacked PRs — **merge gate open**
>>>>>>> cursor/wave-e-signals-macro-4988

| Phase | PR | Status |
|-------|-----|--------|
| 0 Instrumentation | #498 | ✅ |
| 1 Schedulers | #500 | ✅ |
| 2 Score snapshots | #502 | ✅ |
| 3 Shadows / HOLD | #503 | ✅ |
| 4–6 bridges + trust + verify | #504 | ✅ |

## Ops follow-up

<<<<<<< HEAD
- Confirm worker/essential process writes `score_snapshots.json` (snapshot_age non-null)
- `APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/verify_prod.sh`
- Optional: `fly scale count web=1 worker=1`

## Prior (done)

Pump-site + G0 · H1 SSE · Calibration (#494).
=======
<<<<<<< HEAD
1. **Merge #498** (Phase 0)
2. Phase 1 — traffic-independent daily/hour schedulers
3. Phase 2 — `score_snapshots.json`
4. Phases 3–6 per plan gate protocol
>>>>>>> 20db888 (feat(learning): Phase 0 loop health + ledger contract guard)
=======
1. **Merge #508** (Wave E signals + macro overlay)
2. Close stale PRs #455 #491 #487 #474 #449 (human — agent token lacks `closePullRequest`)
3. Learning loop Phase 0 — **#498** (separate agent; not babysit lane)
>>>>>>> 3cc35e6 (docs: board Wave E phased + G0 prod pass)

## Prior (done)

Pump-site Waves 0–3 (#410+). Calibration + 40% gate (#494). H1 SSE (#497). G0 script (#501).

## Human follow-up

- `APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/g0_phone_qa.sh`
- Optional: `fly scale count web=1 worker=1 --app subnet-dashboard`
<<<<<<< HEAD
- G0 human — 390px phone QA sign-off (`./scripts/g0_phone_qa.sh` + manual)
=======
`#498 → #500 → #502 → #503 → #504` then run `./scripts/verify_prod.sh`.

## Prior (done)

Pump-site Waves 0–3 · Calibration + 40% gate (#494).
>>>>>>> 807e94d (feat(learning): Phases 4–6 bridges, trust surface, prod verify)
=======
- Chutes billing for live chat (skipped in babysit)
>>>>>>> 3cc35e6 (docs: board Wave E phased + G0 prod pass)
>>>>>>> cursor/wave-e-signals-macro-4988
