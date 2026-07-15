"""Phase J — direction-first prediction grading (SciWeave J4) + §16.2 hybrid."""

from __future__ import annotations

from typing import Any, Dict, Optional

# SciWeave Phase 2 weights (phase-n-design.md §6)
_DIRECTION_WEIGHT = 0.4
_MAGNITUDE_WEIGHT = 0.6
# Absolute % points: |predicted - actual| / scale → mapped to [0, 1]
MAGNITUDE_SCALE_PCT = 10.0
# Reuse calibration floor (internal/calibration/pipeline.MIN_RESOLVED_SAMPLE)
HYBRID_MIN_SAMPLE = 30


def prediction_direction(prediction: Dict[str, Any]) -> str:
    direction = prediction.get("direction")
    if isinstance(direction, str) and direction.lower() in {"up", "down"}:
        return direction.lower()
    predicted_pct = float(prediction.get("predicted_pct", 0) or 0)
    if predicted_pct < 0:
        return "down"
    if predicted_pct > 0:
        return "up"
    return "up"


def direction_correct(prediction: Dict[str, Any], actual_pct: float) -> bool:
    """SciWeave phase 1: sign-only correctness."""
    direction = prediction_direction(prediction)
    if direction == "up":
        return actual_pct > 0
    return actual_pct < 0


def classify_outcome_direction_only(
    prediction: Dict[str, Any],
    actual_pct: float,
) -> str:
    """Map direction-only grading to legacy hit/miss outcomes."""
    if actual_pct == 0:
        return "miss"
    if direction_correct(prediction, actual_pct):
        return "hit"
    return "miss"


def magnitude_calibration(
    predicted_pct: float,
    actual_pct: float,
    *,
    scale: float = MAGNITUDE_SCALE_PCT,
) -> float:
    """Map magnitude error to [0, 1] (1 = perfect)."""
    scale = float(scale) if scale and scale > 0 else MAGNITUDE_SCALE_PCT
    err = abs(float(predicted_pct) - float(actual_pct))
    return max(0.0, min(1.0, 1.0 - err / scale))


def _gradeable_resolved_count() -> int:
    try:
        from internal.learning.predictions_store import load_predictions

        data = load_predictions()
    except Exception:
        return 0
    n = 0
    skip = frozenset({"duplicate", "expired", "ungradeable"})
    for row in data.get("resolved") or []:
        if not isinstance(row, dict):
            continue
        if row.get("outcome") in skip:
            continue
        if row.get("actual_pct") is None:
            continue
        n += 1
    return n


def hybrid_score_status(
    *,
    min_sample: int = HYBRID_MIN_SAMPLE,
) -> Dict[str, Any]:
    """Gate + reason for API/UI (honest-empty when thin history)."""
    n = _gradeable_resolved_count()
    ok = n >= int(min_sample)
    return {
        "ready": ok,
        "n": n,
        "min_sample": int(min_sample),
        "reason": None if ok else "not_enough_data",
        "message": None if ok else "not enough data yet",
        "formula": "0.4*direction + 0.6*magnitude_calibration",
        "magnitude_scale_pct": MAGNITUDE_SCALE_PCT,
    }


def hybrid_score(
    prediction: Dict[str, Any],
    actual_pct: float,
    *,
    min_sample: int = HYBRID_MIN_SAMPLE,
    sample_n: Optional[int] = None,
) -> Optional[float]:
    """SciWeave hybrid score — None when history below min_sample (no fake float)."""
    n = sample_n if sample_n is not None else _gradeable_resolved_count()
    if n < int(min_sample):
        return None

    direction_score = 1.0 if direction_correct(prediction, float(actual_pct)) else 0.0
    predicted_pct = float(prediction.get("predicted_pct", 0) or 0)
    mag = magnitude_calibration(predicted_pct, float(actual_pct))
    score = _DIRECTION_WEIGHT * direction_score + _MAGNITUDE_WEIGHT * mag
    return round(max(0.0, min(1.0, score)), 4)


def compute_actual_pct(reference_price: float, resolved_price: float) -> float:
    if reference_price <= 0 or resolved_price <= 0:
        return 0.0
    return round((resolved_price - reference_price) / reference_price * 100, 4)
