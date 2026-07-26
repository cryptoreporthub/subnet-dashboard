# Learning Loop Full Integration Plan

**Canonical:** this file  
**Updated:** 2026-07-26  
**Prerequisite:** confidence calibration on `main` (#494; draft #491 superseded)

Closed loop: **pick → predictions.json → resolver → weights/signals → next score**.

## Hard safety rule

Never call `select_daily_pick` / full `score_universe(~127)` on synchronous API handlers. Full-universe scoring belongs in background jobs writing `data/score_snapshots.json`. Keep `PICK_HANDLER_TIMEOUT_SECONDS=8` and default `TOP_SCORING_UNIVERSE=40` on request paths.

## Locked product params

| Param | Value |
|-------|-------|
| Publish gate | 40% `final_confidence` |
| Revision margin | 4 percentage points (live confidence) |
| Live desk review | 3 hours |
| Grading horizon (day) | 4 hours |

## HOLD vs LONG ledger rule

- **Published LONG/BUY** (pick present, action not HOLD) **must** have a matching primary `horizon_type=day` pending/resolved row in `predictions.json`. Gap → `/api/learning/health` `status=stalled`.
- **HOLD** writes trail + optional **shadow** counterfactual (Phase 3). Shadows do not satisfy the LONG ledger requirement and do not enter RF-2.

## Weight writers (quarantine)

| Path | Authority |
|------|-----------|
| `nudge_expert` / `nudge_signal_weight` (+ trail) | Online authority |
| Calibration / `rebalance_council_weights` | Batch OK |
| `message_intel.self_learning.SelfLearning.start_background_learning` | **Quarantined** — not started from `server.py` / `background_boot` |
| Pump overlay / pump_calibration | **Separate track** — never writes `council_weights` |

## Phase STATUS

<<<<<<< HEAD
| Phase | Status | Notes |
|-------|--------|-------|
<<<<<<< HEAD
| 0 Instrumentation | **merged (#498)** | `/api/learning/health`, ledger contract, LB-7/8 verify |
| 1 Schedulers | **in progress** | Traffic-independent daily + hour create |
| 2 Score snapshots | gated on 1 | Full 127 off hot path |
=======
| 0 Instrumentation | **done (PR #498)** | CI green; awaiting merge |
| 1 Schedulers | **done (PR #500)** | stacked on Phase 0; awaiting merge |
| 2 Score snapshots | **in progress** | Full 127 off hot path; cap reads snapshot |
>>>>>>> 573f9da (feat(council): Phase 2 full-universe score snapshots off hot path)
| 3 Shadows / HOLD / Option A | gated on 2 **stable** | Counterfactuals + hero |
| 4 Intel / pump / history | gated on 3 | Bridge into loop |
| 5 UI trust | gated on 4 | RF-2 honesty |
| 6 Validation | gated on 5 | End-to-end + Fly regression |
=======
| Phase | PR | Status |
|-------|-----|--------|
| 0 Instrumentation | #498 | CI green — **awaiting merge** |
| 1 Schedulers | #500 | stacked — awaiting merge |
| 2 Score snapshots | #502 | stacked — awaiting merge |
| 3 Shadows / HOLD | #503 | stacked — awaiting merge |
| 4 Intel / pump / history | #504 (this) | hour #2–3 shadows; readiness bridge |
| 5 UI trust | #504 | RF-2 excludes shadows; ops surfaces loop health |
| 6 Validation | #504 | `scripts/verify_prod.sh` learning-loop checks |
>>>>>>> 807e94d (feat(learning): Phases 4–6 bridges, trust surface, prod verify)

## Phase gate

Next phase starts only after previous is **merged to main** and verify checklist passes. Stacked PRs are ready; **merge order: #498 → #500 → #502 → #503 → #504**.

## Prod verify (Phase 6)

```bash
APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/verify_prod.sh
```

Expect `/api/learning/health` not `stalled` for LONG-without-ledger; snapshot age present after worker cycle; `/health` OK during snapshot job.
