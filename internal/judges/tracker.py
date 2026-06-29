"""
Lifecycle integration between predictions and the judge layer.

- When a prediction is created, each judge opens a sized paper position.
- When a prediction resolves, each judge closes its position and, if the pick
  was wrong, records a scientific-method postmortem.

This feeds the Council learning loop with portfolio-level feedback on top of
expert-weight nudges.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from internal.judges import echo_judge, oracle_judge, pulse_judge
from internal.judges.judges import all_judges


def _actual_pct(prediction: Dict[str, Any]) -> float:
    if "actual_pct" in prediction:
        return float(prediction["actual_pct"] or 0)
    ref = float(prediction.get("reference_price", 0) or 0)
    resolved = float(prediction.get("resolved_price", 0) or 0)
    if ref > 0 and resolved > 0:
        return (resolved - ref) / ref * 100
    return 0.0


def on_prediction_created(
    prediction: Dict[str, Any],
    signal_impact: Optional[Dict[str, Any]] = None,
    subnet: Optional[Dict[str, Any]] = None,
    expert_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Open a paper position in each judge's portfolio.

    Returns the judge scores so callers can store them on the prediction.
    """
    scores = {
        "oracle": oracle_judge.evaluate(prediction, signal_impact=signal_impact, subnet=subnet),
        "echo": echo_judge.evaluate(prediction, signal_impact=signal_impact, expert_weights=expert_weights),
        "pulse": pulse_judge.evaluate(prediction, signal_impact=signal_impact, subnet=subnet),
    }
    for judge in all_judges():
        judge.open_position(prediction)
    return scores


def on_prediction_resolved(prediction: Dict[str, Any]) -> Dict[str, Any]:
    """Close judge positions and record postmortems for wrong picks.

    Returns a summary of judge outcomes for this prediction.
    """
    actual_pct = _actual_pct(prediction)
    outcome = prediction.get("outcome", "unknown")
    wrong = not prediction.get("correct", outcome == "hit")

    summary: Dict[str, Any] = {
        "prediction_id": prediction.get("id"),
        "actual_pct": round(actual_pct, 4),
        "outcome": outcome,
        "wrong": wrong,
        "judges": {},
    }

    for judge in all_judges():
        closed = judge.close_position(prediction, actual_pct=actual_pct, outcome=outcome)
        postmortem = None
        if wrong:
            postmortem = judge.record_postmortem(prediction, actual_pct)
        summary["judges"][judge.name] = {
            "closed": closed,
            "postmortem": postmortem,
        }

    return summary
