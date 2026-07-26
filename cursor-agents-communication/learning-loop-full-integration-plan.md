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

- **Published LONG/BUY** (pick present, action not HOLD) **must** have a matching `horizon_type=day` pending/resolved row in `predictions.json`. Gap → `/api/learning/health` `status=stalled`.
- **HOLD** is trail-only via `record_hold_decision` until Phase 3 shadows. No ledger row required.

## Weight writers (quarantine)

| Path | Authority |
|------|-----------|
| `nudge_expert` / `nudge_signal_weight` (+ trail) | Online authority |
| Calibration / `rebalance_council_weights` | Batch OK |
| `message_intel.self_learning.SelfLearning.start_background_learning` | **Quarantined** — not started from `server.py` / `background_boot` |

## Phase STATUS

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

## Phase gate

Next phase starts only after previous is **merged to main** and verify checklist passes (contract tests, `/api/learning/health`, `/health`, Ditto STATUS).

## Phase summaries

### 0 — Instrumentation
`GET /api/learning/health`: pending, last resolver tick, daily pick, ledger gap, snapshot age, status ok/degraded/stalled. No behavior change.

### 1 — Schedulers
Background daily + hour pick creation. Keep `GET /api/daily-pick` read-only.

### 2 — Score snapshots
Worker writes `data/score_snapshots.json`; APIs read it. Never raise scoring cap on request path.

### 3 — Shadows + HOLD + Option A
Grade near-calls/HOLD candidates as shadows (excluded from RF-2); harden live-desk hero on HOLD.

### 4 — Bridges
Message-intel / pump (keep pump weights separate) / rotation / pick history into learning surfaces.

### 5 — UI trust
Trust banner + Living Focus only gated RF-2 stats.

### 6 — Validation
Cross-phase regression + prod day checklist.
