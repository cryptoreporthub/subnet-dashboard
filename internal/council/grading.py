"""Phase J — direction-first prediction grading (SciWeave J4)."""

from __future__ import annotations

from typing import Any, Dict, Optional


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


def compute_actual_pct(reference_price: float, resolved_price: float) -> float:
    if reference_price <= 0 or resolved_price <= 0:
        return 0.0
    return round((resolved_price - reference_price) / reference_price * 100, 4)
