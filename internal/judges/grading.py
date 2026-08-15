"""Per-judge selective grading for weight nudges (meta-labeling gates).

Judges endorse council picks when score >= threshold. A good abstain on a miss
counts as correct; endorsing a miss counts as wrong — same rule as backtest.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from internal.council.grading import direction_correct

JUDGE_THRESHOLDS: Dict[str, float] = {
    "oracle": 0.55,
    "echo": 0.5,
    "pulse": 0.55,
}

_MIN_PRED_PCT = 0.5
_MAX_MOVE_SCALE = 3.0
_MIN_CONVICTION_SCALE = 0.25


def judge_threshold(judge: str) -> float:
    return JUDGE_THRESHOLDS.get(judge, 0.55)


def judge_endorsed(score: float, judge: str) -> bool:
    return float(score) >= judge_threshold(judge)


def judge_score_at_creation(prediction: Dict[str, Any], judge: str) -> Optional[float]:
    scores = prediction.get("judge_scores_at_creation")
    if not isinstance(scores, dict):
        return None
    block = scores.get(judge)
    if not isinstance(block, dict) or block.get("score") is None:
        return None
    try:
        return float(block["score"])
    except (TypeError, ValueError):
        return None


def judge_nudge_correct(
    prediction: Dict[str, Any],
    judge: str,
    actual_pct: float,
    *,
    pnl_pct: Optional[float] = None,
) -> bool:
    """Whether this judge's endorsement decision matched the council outcome."""
    score = judge_score_at_creation(prediction, judge)
    if score is not None:
        council_hit = direction_correct(prediction, actual_pct)
        endorsed = judge_endorsed(score, judge)
        return council_hit if endorsed else not council_hit
    # ponytail: legacy rows without stored scores — fall back to portfolio PnL sign
    if pnl_pct is not None:
        return float(pnl_pct) > 0
    return direction_correct(prediction, actual_pct)


def judge_nudge_magnitude_scale(
    prediction: Dict[str, Any],
    actual_pct: float,
    correct: bool,
    judge: Optional[str] = None,
    *,
    pnl_pct: Optional[float] = None,
) -> float:
    """Scale a nudge by market move and, when available, judge conviction.

    Rows created before judge scores were persisted retain the shared market
    move scale. New rows use the judge's distance from its endorsement
    threshold so a confident wrong judge receives a larger penalty than a
    near-threshold abstention.
    """
    actual = abs(float(actual_pct or 0))
    predicted = abs(float(prediction.get("predicted_pct") or 0))
    ratio = actual / max(predicted, _MIN_PRED_PCT)
    ratio = min(_MAX_MOVE_SCALE, ratio)
    if ratio > 1.0:
        ratio = 1.0 + math.log(ratio)
    if not correct:
        ratio = max(1.0, ratio)
    if judge:
        score = judge_score_at_creation(prediction, judge)
        if score is not None:
            conviction = abs(score - judge_threshold(judge)) * 2.0
            ratio *= max(_MIN_CONVICTION_SCALE, min(1.0, conviction))
        elif pnl_pct is not None:
            # Legacy rows have no score; preserve their move scale while
            # preventing a zero-PnL position from creating a zero nudge.
            conviction = abs(float(pnl_pct)) / max(actual, 1.0)
            ratio *= max(_MIN_CONVICTION_SCALE, min(1.0, conviction))
    return round(ratio, 4)
