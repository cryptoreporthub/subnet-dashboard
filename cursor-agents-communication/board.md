# Subnet Dashboard Coordination Board

<<<<<<< HEAD
**Last updated:** 2026-07-26T16:55:00Z  
**main:** `083f456` · G0 prod green · cockpit SSE fast path (#497)
=======
**Last updated:** 2026-07-26T16:50:00Z  
**main:** see git (`#494` calibration + follow-ups)
>>>>>>> 20db888 (feat(learning): Phase 0 loop health + ledger contract guard)

## Active plan

**Canonical:** `cursor-agents-communication/learning-loop-full-integration-plan.md`  
**Status:** Phase **0** done (PR #498) — awaiting merge

<<<<<<< HEAD
| Wave | Status | Notes |
|------|--------|-------|
| 0 G0 | ✅ | `./scripts/g0_phone_qa.sh` prod green 2026-07-26 · 390px visual QA local pass |
| 1 P1–P3 | ✅ | Triad, hit-rate UI, size cliff (#410) |
| 2 P4–P5 | ✅ | Phase notify ✅ · wallet + day-whale + owner chips |
| 3 S1–S8 | ✅ | All merged #410; S3 who-sold = Prove-it button only |
| 4 | — | YAGNI |
| H1 | ✅ | cockpit.picks SSE + hour-watch rib (#497 SSE fix) |

**Execution history:** PR **#410** (Cursor Cloud Agent, 2026-07-22) + #430–#437 whale/Fly + #442–#446 site polish.

## Next slice queue

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

## Next slice queue

1. **Merge #498** (Phase 0)
2. Phase 1 — traffic-independent daily/hour schedulers
3. Phase 2 — `score_snapshots.json`
4. Phases 3–6 per plan gate protocol
>>>>>>> 20db888 (feat(learning): Phase 0 loop health + ledger contract guard)

## Prior (done)

Pump-site Waves 0–3 shipped (#410 + follow-ups). Calibration + 40% gate on main (#494).  
H1 SSE cockpit fast path (#497).

## Human follow-up

- Merge Phase 0 PR when CI green, then unlock Phase 1
- Optional: `fly scale count web=1 worker=1 --app subnet-dashboard`
- G0 human — 390px phone QA sign-off (`./scripts/g0_phone_qa.sh` + manual)
