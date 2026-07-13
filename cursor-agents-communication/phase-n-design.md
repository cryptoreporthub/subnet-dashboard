# Phase N — Calibration / Retrain (Grok design → Composer spec)

**Date:** 2026-07-13  
**Model:** grok-4.5-xhigh design pass → Composer build → Grok-xhigh safety review  
**Stack:** FastAPI + Uvicorn (`server:app`)  
**main:** `a758035` (post-Phase M)

## Verdict: ✅ PROCEED

Phase J fixed grading, dedupe, symmetric nudges, and atomic resolution. Phase N adds a **batch** retrain path (Retrain → Cert → Fire) that sits **beside** the online `_nudge_weights` loop — it does not replace or rewrite the resolver. Weights already persist in `data/soul_map.json` (`adversarial_state.council_weights`); there is no separate `weights.json`.

---

## 1. What “retrain” means

| Concept | Definition |
|---------|------------|
| **Online learning (existing)** | Per-resolve `+0.02/−0.02` nudge in `resolver._nudge_weights` |
| **Batch retrain (Phase N)** | Re-fit `council_weights` from **resolved** predictions in `data/predictions.json` |

**Retrain computes** new expert weights from historical outcomes:

1. Load `resolved` rows from `predictions.json` (post-J replay stream).
2. Exclude `duplicate`, `expired`, `ungradeable` rows (R2 dedupe respected).
3. Map each row’s `expert` → canonical lane (`quant`, `hype`, `dark_horse`, `technical`) via `resolver._expert_key`.
4. Per expert: direction-only correctness (`grading.direction_correct`) on gradeable rows.
5. Proposed weight = Laplace-smoothed accuracy scaled to `[0.3, 2.0]` with max expert ratio ≤ 2×.

**What gets updated:** `adversarial_state.council_weights` + mirrored `expert_weights` (existing `save_weights`). **Not** signal_weights (separate online tier; out of scope for N).

**What does NOT change:** resolver grading, dedupe, horizon logic, or online nudge constants.

---

## 2. Data sources

| Source | Use |
|--------|-----|
| **`data/predictions.json`** | ✅ **Primary** — `resolved` bucket, `correct`, `expert`, `direction`, `actual_pct` |
| **`data/judge_portfolios.json`** | ❌ Read-only validation optional; not weight training input |
| **Batch/stale artifacts** | ❌ Never — only live predictions store |

**Dedup:** Apply `deduplication.mark_duplicates_in_resolved` before training; rows with `status=="duplicate"` are excluded.

**Minimum sample:** `MIN_RESOLVED_SAMPLE = 30` (SciWeave Q11 regime minimum). Below this → cert **fails** with honest-empty status, no fire.

---

## 3. Pipeline: Retrain → Cert → Fire

```
POST /api/calibration/retrain  (or scheduler tick)
  │
  ├─► [Retrain]  load_training_rows() → compute_proposed_weights()
  │
  ├─► [Cert]     backtest_holdout() + sanity_checks()
  │       ├─ PASS → continue
  │       └─ FAIL → log, update calibration state, return (old weights untouched)
  │
  └─► [Fire]     atomic_swap_weights(proposed)
        ├─ backup current weights in calibration state
        ├─ save_weights(proposed)  [existing os.replace atomic write]
        ├─ verify load_weights() == proposed
        ├─ emit trail event weight_change / calibration_retrain
        └─ on verify fail → rollback save_weights(backup)
```

**Scheduling:**

| Mode | Trigger |
|------|---------|
| **Manual** | `POST /api/calibration/retrain` (admin-guarded) |
| **Auto (optional)** | `CalibrationScheduler` daemon thread; fires when `resolved_since_last_retrain >= 30` AND `CALIBRATION_AUTO_RETRAIN=on` |
| **Default** | Manual only; scheduler off in CI (`CALIBRATION_AUTO_RETRAIN` unset) |

Cadence: no cron on Fly by default — piggyback on resolver scheduler optional hook (post-tick check, non-blocking).

---

## 4. Certification checklist

### 4.1 Backtest (holdout)

- Window: last `CERT_BACKTEST_N = 50` deduped gradeable resolved rows (or all if fewer).
- Metric: **direction accuracy** using proposed weights vs current weights.
  - For each row: weight the row’s expert by lane weight; pick weighted majority direction; compare to `actual_pct` sign.
  - Simpler lane metric: per-expert accuracy × proposed weight sum (same as training objective).
- **Pass rule:** `proposed_accuracy >= current_accuracy` on the same holdout (no threshold gaming).
- **Sample rule:** `gradeable_count >= MIN_RESOLVED_SAMPLE` (30).

### 4.2 Sanity checks (hard fail)

| Check | Threshold | Source |
|-------|-----------|--------|
| Weight floor | `min(w) >= 0.3` | SciWeave J5 / `resolver._LEARNING_MIN_WEIGHT` |
| Weight ceiling | `max(w) <= 2.0` | `resolver._LEARNING_MAX_WEIGHT` |
| Max ratio | `max(w) / min(w) <= 2.0` | User spec |
| Canonical experts | all four keys present | `DEFAULT_WEIGHTS` |
| No NaN/negative | all finite, `> 0` | — |

### 4.3 On cert FAIL

- **Do not fire.** Current weights remain active.
- Persist cert report in `adversarial_state.calibration.last_cert`.
- Trail event: `calibration_cert_failed` with evidence.
- API returns `{"status": "cert_failed", "cert": {...}}`.

---

## 5. Atomic swap mechanism

Reuse `internal/council/weights.py`:

```python
# weights._save_raw: write .tmp → os.replace(path)
save_weights(proposed)  # atomic at filesystem level
```

**Fire sequence:**

1. `backup = load_weights()`
2. `save_weights(proposed)` — single atomic replace of `soul_map.json`
3. `verify = load_weights()` — must match proposed within `1e-4`
4. On mismatch: `save_weights(backup)` and raise `FireError`
5. Update `adversarial_state.calibration` metadata (separate read-modify-write on same file — acceptable; weights already committed)

**Crash safety:** If process dies between steps 2–5, worst case new weights are live (cert already passed) or old weights remain (if save never completed). No partial weight dict — `save_weights` writes complete JSON object.

**Hot-path isolation:** Retrain runs in a **daemon thread** with module-level `_retrain_lock`. Resolver calls `load_weights()` per nudge — never blocks on retrain lock.

---

## 6. Calibration scoring — J4 Phase 2 (deferred)

| Phase | Grading | Status |
|-------|---------|--------|
| **Phase 1** | Direction-only (`grading.direction_correct`) | ✅ Live (J) |
| **Phase 2** | `0.4 × direction + 0.6 × magnitude_calibration` | ⏸ **Deferred** |

**Blocker:** `_predicted_pct_from_pick()` is still a confidence proxy (`prediction_loop.py`). Enabling magnitude scoring now would violate SciWeave Q4.

**Phase N scope:** Retrain and cert use **direction-only** accuracy (same as resolver). Add `grading.hybrid_score()` stub returning `None` when magnitude not signal-derived; wire in Phase O when `state_vector` emits real magnitude.

---

## 7. API surface

### `GET /api/calibration/status`

```json
{
  "status": "ok",
  "weights": {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0},
  "calibration": {
    "last_retrain_at": "2026-07-13T02:00:00Z",
    "last_cert_status": "passed",
    "last_cert_accuracy": {"proposed": 0.52, "current": 0.48},
    "resolved_sample": 45,
    "retrain_in_progress": false,
    "auto_retrain_enabled": false
  },
  "thresholds": {
    "min_sample": 30,
    "weight_floor": 0.3,
    "weight_ceiling": 2.0,
    "max_expert_ratio": 2.0
  }
}
```

### `POST /api/calibration/retrain`

**Guard:** `CALIBRATION_ADMIN_TOKEN` env. If set, require header `X-Calibration-Token: <token>`. If unset (dev/CI), allow with `dry_run` default safe.

Body (optional):

```json
{"dry_run": false, "force": false}
```

- `dry_run: true` — run Retrain + Cert only; never Fire.
- `force: true` — skip cert (dev only; ignored when `CALIBRATION_ADMIN_TOKEN` set in prod).

Response:

```json
{
  "status": "fired",
  "proposed_weights": {...},
  "cert": {"passed": true, "proposed_accuracy": 0.52, "current_accuracy": 0.48},
  "fired_at": "..."
}
```

### Optional: `GET /api/calibration/history`

Last 5 retrain events from calibration state (YAGNI — include in status `history` array instead).

---

## 8. Trace / dashboard visibility

Emit via `internal/learning/trail_bus.py`:

```python
emit_trail_event(
    "weight_change",
    signal="calibration_retrain",
    evidence={"before": backup, "after": proposed, "cert": cert_report},
    decision="retrain_fired" | "cert_failed",
)
```

Cockpit: no template changes this slice. `/api/mindmap/trail` picks up events. `/api/calibration/status` is the primary consumer.

---

## 9. File list (Composer)

| Action | Path |
|--------|------|
| **Create** | `internal/calibration/__init__.py` |
| **Create** | `internal/calibration/pipeline.py` — retrain, cert, fire, state, lock |
| **Create** | `internal/calibration/routes.py` — status + retrain endpoints |
| **Modify** | `internal/learning/routes.py` — `include_router(calibration_router)` |
| **Create** | `tests/test_phase_n_calibration.py` |
| **Modify** | `tests/test_endpoint_contract.py` — add GET status, POST retrain dry_run |
| **Create** | `cursor-agents-communication/phase-n-design.md` (this file) |
| **Create** | `cursor-agents-communication/phase-n-safety-review.md` (Step C) |

**Do not modify:** `resolver.py` core, templates, CSS, H-full UI.

---

## 10. Function signatures

```python
# internal/calibration/pipeline.py

MIN_RESOLVED_SAMPLE: int = 30
CERT_BACKTEST_N: int = 50
WEIGHT_FLOOR: float = 0.3
WEIGHT_CEILING: float = 2.0
MAX_EXPERT_RATIO: float = 2.0

def load_training_rows(
    predictions_path: str = "data/predictions.json",
) -> list[dict[str, Any]]: ...

def compute_proposed_weights(
    rows: list[dict[str, Any]],
    *,
    floor: float = WEIGHT_FLOOR,
    ceiling: float = WEIGHT_CEILING,
    max_ratio: float = MAX_EXPERT_RATIO,
) -> dict[str, float]: ...

def certify_weights(
    proposed: dict[str, float],
    rows: list[dict[str, Any]],
    *,
    current: dict[str, float] | None = None,
    min_sample: int = MIN_RESOLVED_SAMPLE,
    backtest_n: int = CERT_BACKTEST_N,
) -> dict[str, Any]: ...
# Returns {"passed": bool, "proposed_accuracy": float, "current_accuracy": float, ...}

def fire_weights(
    proposed: dict[str, float],
    *,
    soul_map_path: str = "data/soul_map.json",
) -> dict[str, float]:
    """Atomic swap with verify + rollback. Returns fired weights."""

def run_calibration_pipeline(
    *,
    dry_run: bool = False,
    force: bool = False,
    soul_map_path: str = "data/soul_map.json",
    predictions_path: str = "data/predictions.json",
) -> dict[str, Any]: ...

def get_calibration_status(
    soul_map_path: str = "data/soul_map.json",
) -> dict[str, Any]: ...

def start_retrain_async(**kwargs) -> dict[str, Any]:
    """Spawn daemon thread; return {"started": True, "in_progress": True}."""
```

```python
# internal/calibration/routes.py

calibration_router = APIRouter(tags=["calibration"])

@calibration_router.get("/api/calibration/status") -> dict: ...
@calibration_router.post("/api/calibration/retrain") -> dict: ...
```

---

## 11. Risk mitigation

| Failure | Handling |
|---------|----------|
| Insufficient resolved sample (<30) | Cert fails; status reports `insufficient_data`; no fire |
| Cert accuracy regression | Cert fails; old weights kept |
| Sanity violation (ratio >2×) | `compute_proposed_weights` compresses; if still fails cert, no fire |
| `save_weights` IOError | Fire aborts; backup restored if partial verify fails |
| Retrain during resolver tick | Independent `load_weights` reads; lock only serializes retrains |
| Concurrent POST retrain | `_retrain_lock` — second request returns `409 in_progress` |
| `force=true` in prod | Ignored when `CALIBRATION_ADMIN_TOKEN` set |
| Magnitude gaming | Direction-only cert; J4 Phase 2 gated on signal magnitude |
| Stale pre-J data | Training excludes non-gradeable; replay-normalized rows only |

---

## 12. Tests (Composer)

`tests/test_phase_n_calibration.py`:

1. `test_compute_proposed_weights_respects_floor_and_ceiling`
2. `test_cert_fails_insufficient_sample`
3. `test_cert_fails_when_proposed_worse_than_current`
4. `test_cert_passes_when_proposed_better`
5. `test_fire_atomic_swap_and_rollback_on_verify_fail` (monkeypatch verify)
6. `test_dry_run_never_writes_weights`
7. `test_dedupe_rows_excluded_from_training`
8. `test_status_endpoint_shape`

Contract: `GET /api/calibration/status`, `POST /api/calibration/retrain` with `{"dry_run": true}`.

---

## 13. Acceptance criteria

- [ ] Retrain produces weights that pass certification or rolls back
- [ ] Weight swap is atomic — no partial state on crash (verify + rollback test)
- [ ] `GET /api/calibration/status` returns weights + last retrain info
- [ ] Tests pass; `/health` returns OK
- [ ] No thresholds lowered to fake accuracy
- [ ] Resolver hot path not blocked (async retrain + lock isolation)

---

*Design: Phase N highest-risk slice per model-guide.md §4. Implementation: Composer. Review: Grok-xhigh before merge.*
