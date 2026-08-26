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


class _SkipJudgeNudge(Exception):
    """Internal: skip this judge nudge without treating it as an error."""


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
        block = scores.get(judge.name) or {}
        conf = float(block.get("confidence", 0.5) or 0.5)
        judge.open_position(prediction, size=0.5 + 0.5 * conf)
    return scores


def on_prediction_resolved(
    prediction: Dict[str, Any],
    *,
    apply_judge_nudge: bool = True,
) -> Dict[str, Any]:
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
        if closed and apply_judge_nudge:
            try:
                from internal.council.grading import is_pump_desk_claim
                from internal.judges.grading import (
                    judge_nudge_correct,
                    judge_nudge_magnitude_scale,
                )
                from internal.judges.weights import nudge_judge

                if is_pump_desk_claim(prediction) or prediction.get("shadow") or prediction.get("counterfactual"):
                    raise _SkipJudgeNudge()
                from internal.council.capture import (
                    capture_from_row,
                    capture_mode_enabled,
                    capture_nudge_correct,
                    nudge_multiplier,
                )

                correct = judge_nudge_correct(
                    prediction,
                    judge.name,
                    actual_pct,
                    pnl_pct=closed.get("pnl_pct"),
                )
                extra = None
                if capture_mode_enabled():
                    cap = capture_from_row(prediction)
                    flag = capture_nudge_correct(cap)
                    if flag is None:
                        raise _SkipJudgeNudge()
                    correct = flag
                    mult = nudge_multiplier(cap)
                    if mult is None:
                        raise _SkipJudgeNudge()
                    # Same multiplier as expert/signal (HIT 1.0 / NEAR-HIT c / MISS 1.0).
                    scale = float(mult)
                    extra = {"band": cap.band, "capture": cap.capture_capped}
                else:
                    scale = judge_nudge_magnitude_scale(
                        prediction,
                        actual_pct,
                        correct,
                        judge.name,
                        pnl_pct=closed.get("pnl_pct"),
                    )
                nudge_judge(
                    judge.name,
                    correct=correct,
                    scale=scale,
                    actual_pct=actual_pct,
                    extra=extra,
                )
            except _SkipJudgeNudge:
                pass
            except Exception:
                pass
        postmortem = None
        if wrong:
            postmortem = judge.record_postmortem(prediction, actual_pct)
        summary["judges"][judge.name] = {
            "closed": closed,
            "postmortem": postmortem,
        }
        try:
            from internal.learning.trail_bus import emit_judge_pnl, emit_judge_postmortem

            emit_judge_pnl(judge.name, prediction, closed)
            if postmortem:
                emit_judge_postmortem(judge.name, prediction, postmortem)
        except Exception:
            pass

    return summary
