"""
Echo Judge — assesses resonance / consensus patterns across signals.

Echo looks at how strongly the directional voices in a signal set agree with
each other and with the final prediction. Strong consensus yields a higher
score; fractured or contradictory signals lower it.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Optional


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def evaluate(
    prediction: Dict[str, Any],
    signal_impact: Optional[Dict[str, Any]] = None,
    expert_weights: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """Return Echo score and confidence for a prediction.

    Score is higher when:
      - most impact signals share the same direction as the prediction,
      - the dominant impact direction matches the prediction,
      - the originating expert has an above-average weight.

    Confidence rises with the number of signals considered.
    """
    signal_impact = signal_impact or {}
    expert_weights = expert_weights or {}

    impacts = signal_impact.get("impacts", []) or []
    if not impacts:
        return {"score": 0.5, "confidence": 0.25}

    directions = [str(i.get("direction", "neutral")).lower() for i in impacts]
    counts = Counter(directions)
    total = len(directions)

    pred_direction = prediction.get("direction", "up")
    target = "bullish" if pred_direction == "up" else "bearish" if pred_direction == "down" else "neutral"

    agreement = counts.get(target, 0) / total if total else 0.0
    dominant = signal_impact.get("net_direction", "neutral")
    dominant_match = 1.0 if dominant == target else 0.4

    expert = prediction.get("expert", "technical")
    weight = float(expert_weights.get(expert, 1.0) or 1.0)
    weight_factor = _clamp(weight / 1.5)

    score = _clamp(0.35 + 0.4 * agreement + 0.15 * dominant_match + 0.1 * weight_factor)
    confidence = _clamp(0.4 + 0.4 * min(total / 8.0, 1.0) + 0.2 * agreement)
    return {"score": round(score, 4), "confidence": round(confidence, 4)}
