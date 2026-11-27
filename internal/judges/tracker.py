"""
Lifecycle integration between predictions and the judge layer.

- When a prediction is created, each judge opens a sized paper position.
- When a prediction resolves, each judge closes its position and, if the pick
  was wrong, records a scientific-method postmortem.

This feeds the Council learning loop with portfolio-level feedback on top of
expert-weight nudges.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from internal.judges import echo_judge, oracle_judge, pulse_judge
from internal.judges.judges import all_judges
from internal.judges.postmortems import PostmortemFileCorrupt, list_for_judge

logger = logging.getLogger(__name__)


class _SkipJudgeNudge(Exception):
    """Internal: skip this judge nudge without treating it as an error."""


def _postmortem_already_recorded(judge_name: str, prediction_id: Any) -> bool:
    """True when this judge already has a postmortem row for the prediction."""
    if prediction_id is None:
        # Replay cannot match a missing id; skip so record() does not append again.
        return True
    try:
        rows = list_for_judge(judge_name)
    except PostmortemFileCorrupt:
        return True
    except ValueError:
        return True
    return any(
        isinstance(row, dict) and row.get("prediction_id") == prediction_id
        for row in rows
    )


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
        # close_position returns None on replay. First-pass lock timeout still
        # needs a later record; skip only when this prediction already has a row.
        postmortem_error = None
        should_record = bool(wrong) and (
            bool(closed)
            or (
                closed is None
                and not _postmortem_already_recorded(judge.name, prediction.get("id"))
            )
        )
        if should_record:
            try:
                postmortem = judge.record_postmortem(prediction, actual_pct)
            except Exception as exc:
                from internal.judges.postmortems import (
                    PostmortemFileCorrupt,
                    PostmortemLockTimeout,
                )

                if not isinstance(exc, (PostmortemFileCorrupt, PostmortemLockTimeout)):
                    raise
                logger.error(
                    "postmortem skipped judge=%s prediction=%s: %s",
                    judge.name,
                    prediction.get("id"),
                    exc,
                )
                postmortem = None
                postmortem_error = type(exc).__name__
                try:
                    from internal.learning.trail_events import emit_trail_event

                    emit_trail_event(
                        "postmortem_skipped",
                        judge=judge.name,
                        evidence={
                            "prediction_id": prediction.get("id"),
                            "error_type": postmortem_error,
                        },
                    )
                except Exception:
                    logger.exception(
                        "postmortem_skipped trail emit failed judge=%s prediction=%s",
                        judge.name,
                        prediction.get("id"),
                    )
        judge_summary: Dict[str, Any] = {
            "closed": closed,
            "postmortem": postmortem,
        }
        if postmortem_error:
            judge_summary["postmortem_error"] = postmortem_error
        summary["judges"][judge.name] = judge_summary
        try:
            from internal.learning.trail_bus import emit_judge_pnl, emit_judge_postmortem

            emit_judge_pnl(judge.name, prediction, closed)
            if postmortem:
                emit_judge_postmortem(judge.name, prediction, postmortem)
        except Exception:
            pass

    return summary
