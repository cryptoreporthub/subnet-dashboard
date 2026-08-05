"""Replay judge weight nudges over resolved predictions (P1 backtest gate)."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from internal.judges.grading import judge_nudge_correct, judge_nudge_magnitude_scale
from internal.judges.weights import (
    DEFAULT_JUDGE_WEIGHTS,
    _LEARNING_DELTA_CORRECT,
    _LEARNING_DELTA_WRONG,
    _LEARNING_MAX_WEIGHT,
    _LEARNING_MIN_WEIGHT,
)

JUDGES = ("oracle", "echo", "pulse")
_SKIP_OUTCOMES = frozenset({"duplicate", "expired", "ungradeable"})


def _gradeable_rows(resolved: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in resolved:
        if not isinstance(row, dict):
            continue
        if row.get("outcome") in _SKIP_OUTCOMES:
            continue
        if row.get("status") not in (None, "resolved"):
            continue
        if row.get("actual_pct") is None:
            continue
        rows.append(row)
    return rows


def _apply_nudge(weights: Dict[str, float], judge: str, delta: float) -> None:
    weights[judge] = round(
        max(_LEARNING_MIN_WEIGHT, min(_LEARNING_MAX_WEIGHT, weights[judge] + delta)),
        4,
    )


def replay_judge_weights(
    rows: List[Dict[str, Any]],
    *,
    magnitude_aware: bool = False,
    start: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """Rebuild raw judge weights by replaying selective grading nudges."""
    weights = dict(start or DEFAULT_JUDGE_WEIGHTS)
    for row in _gradeable_rows(rows):
        actual = float(row["actual_pct"])
        for judge in JUDGES:
            correct = judge_nudge_correct(row, judge, actual)
            scale = (
                judge_nudge_magnitude_scale(row, actual, correct)
                if magnitude_aware
                else 1.0
            )
            base = _LEARNING_DELTA_CORRECT if correct else _LEARNING_DELTA_WRONG
            _apply_nudge(weights, judge, round(base * scale, 4))
    return weights


def normalized_entropy(weights: Dict[str, float]) -> float:
    """Shannon entropy of normalized weights (0 = collapsed, ln(3) ≈ 1.1 = uniform)."""
    total = sum(max(0.0, float(v)) for v in weights.values())
    if total <= 0:
        return 0.0
    ent = 0.0
    for v in weights.values():
        p = max(0.0, float(v)) / total
        if p > 0:
            ent -= p * math.log(p)
    return round(ent, 4)


def replay_divergence_report(
    rows: List[Dict[str, Any]],
    *,
    start: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Compare flat vs magnitude-aware replay — gate before enabling P1 in prod."""
    flat = replay_judge_weights(rows, magnitude_aware=False, start=start)
    scaled = replay_judge_weights(rows, magnitude_aware=True, start=start)
    spread_flat = max(flat.values()) - min(flat.values())
    spread_scaled = max(scaled.values()) - min(scaled.values())
    return {
        "sample_size": len(_gradeable_rows(rows)),
        "flat_weights": flat,
        "magnitude_weights": scaled,
        "flat_spread": round(spread_flat, 4),
        "magnitude_spread": round(spread_scaled, 4),
        "flat_entropy": normalized_entropy(flat),
        "magnitude_entropy": normalized_entropy(scaled),
        "diverged": spread_scaled > spread_flat or spread_scaled > 0.02,
    }
