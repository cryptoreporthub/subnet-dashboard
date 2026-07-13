# Phase N — Hot-Path Safety Review (Grok-xhigh)

**Date:** 2026-07-13  
**Reviewer:** grok-4.5-xhigh read-only pass  
**Branch:** `cursor/phase-n-calibration-retrain-42f7`  
**Scope:** `internal/calibration/*`, `internal/learning/routes.py` (router include only)

## Verdict: **PASS**

Phase N extends the learning loop with a batch Retrain → Cert → Fire pipeline. It does not modify `resolver.py` core logic. Hot-path isolation, atomic weight swap, and honest cert thresholds are correctly implemented.

---

## 1. Atomic swap

| Check | Result | Location |
|-------|--------|----------|
| Write uses `os.replace` via `weights._save_raw` | ✅ | `internal/council/weights.py:81-87` |
| Fire verifies post-read before committing state | ✅ | `internal/calibration/pipeline.py:fire_weights` |
| Rollback on verify mismatch | ✅ | `save_weights(backup)` before `FireError` |
| Partial weight dict impossible | ✅ | Full `soul_map.json` replaced atomically |

**Finding:** Calibration metadata (`adversarial_state.calibration`) is updated in a second read-modify-write after weights fire. If crash occurs between weight save and metadata update, new weights remain live (cert already passed) — acceptable.

---

## 2. Hot-path non-blocking

| Check | Result | Location |
|-------|--------|----------|
| Default POST uses daemon thread | ✅ | `start_retrain_async` → `threading.Thread(daemon=True)` |
| `_retrain_lock` serializes retrains only | ✅ | `pipeline.py` — resolver never acquires this lock |
| Resolver `load_weights()` independent per nudge | ✅ | Existing pattern unchanged |
| `dry_run` / contract tests run synchronously | ✅ | `async: false` in contract |

**Finding:** None. Resolver scheduler and prediction loop are not blocked.

---

## 3. Rollback on simulated crash

| Scenario | Result |
|----------|--------|
| Verify fail after save | ✅ Test `test_fire_rollback_on_verify_fail` — weights restored |
| Cert fail | ✅ Old weights untouched (`cert_failed` path) |
| FireError | ✅ `fire_failed` status; backup weights on disk |

---

## 4. Threshold gaming

| Check | Result |
|-------|--------|
| Cert requires `proposed_accuracy >= current_accuracy` | ✅ No fixed low bar |
| `MIN_RESOLVED_SAMPLE = 30` | ✅ SciWeave binding |
| Sanity floor 0.3, ceiling 2.0, ratio ≤ 2× | ✅ |
| `force=true` disabled when `CALIBRATION_ADMIN_TOKEN` set | ✅ |
| J4 Phase 2 magnitude deferred | ✅ Direction-only cert |

**Finding:** None. No thresholds lowered.

---

## 5. Data integrity

| Check | Result |
|-------|--------|
| Training from `predictions.json` resolved only | ✅ |
| Excludes duplicate/expired/ungradeable | ✅ |
| Dedup via `mark_duplicates_in_resolved` | ✅ R2 |
| `judge_portfolios.json` not used as training input | ✅ |

---

## 6. Trace logging

| Check | Result |
|-------|--------|
| Retrain emits `weight_change` trail event | ✅ `_emit_retrain_trail` |
| Cert fail logged | ✅ `decision="cert_failed"` |
| Calibration state history (last 5) | ✅ `_save_calibration_state` |

---

## 7. API surface

| Route | Guard | Result |
|-------|-------|--------|
| `GET /api/calibration/status` | Public read | ✅ |
| `POST /api/calibration/retrain` | `X-Calibration-Token` when env set | ✅ |
| Concurrent retrain | 409 when in progress | ✅ |

---

## 8. Minor notes (non-blocking)

1. **CONDITIONAL (informational):** `_weighted_accuracy` is expert-row weighted; when holdout is single-expert dominated, accuracy ratio can be insensitive to that expert's weight scale. Mixed-expert holdouts behave correctly. Acceptable for N; consider council-level simulation in Phase O.

2. **CONDITIONAL (informational):** `LearningEngine.record_feedback` still uses asymmetric `+0.02/-0.03` and floor `0.1` — pre-J legacy path, out of N scope. Resolver nudges are symmetric per J5.

---

## Summary

| Area | Status |
|------|--------|
| Atomic swap | PASS |
| Hot-path isolation | PASS |
| Rollback | PASS |
| No threshold gaming | PASS |
| Data integrity | PASS |

**Merge recommendation:** ✅ Approve after CI green.

---

*Review model: grok-4.5-xhigh. Implementation: Composer per `phase-n-design.md`.*
