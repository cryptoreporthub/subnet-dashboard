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

| Phase | PR | Status |
|-------|-----|--------|
| 0 Instrumentation | #498 | **merged** — `/api/learning/health`, ledger contract |
| 1 Schedulers | #500 | **merged** — traffic-independent daily + hour picks |
| 2 Score snapshots | #502 | **merged** — full universe off hot path |
| 3 Shadows / HOLD | #503 | **merged** — counterfactuals + hero |
| 4 Intel / pump / history | #504 | **merged** — hour #2–3 shadows; readiness bridge |
| 5 UI trust | #504 | **merged** — RF-2 honesty |
| 6 Validation | #504, #518–#523 | **merged** — `verify_prod.sh`, `check_learning_loop.sh` |

## Phase gate

All phases **merged to main** as of 2026-07-27. Follow-up hardening: CI learning-loop tests, heavy-job mutex, deploy warm scripts.

## Prod verify (Phase 6)

```bash
APP_BASE_URL=https://subnet-dashboard.fly.dev ./scripts/verify_prod.sh
```

Expect `/api/learning/health` not `stalled` for LONG-without-ledger; snapshot age present after worker cycle; `/health` OK during snapshot job.
