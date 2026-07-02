"""
Oracle Judge — evaluates signals for truthfulness / evidentiary quality.

Scores are based on how well a prediction's supporting evidence aligns with
observable subnet metrics (indicators, fundamentals, social data). Confidence
rises when the input record is complete and coherent.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def evaluate(
    prediction: Dict[str, Any],
    signal_impact: Optional[Dict[str, Any]] = None,
    subnet: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    """Return Oracle score and confidence for a prediction.

    Score is higher when:
      - the signal impact has multiple non-neutral impacts,
      - the price-change sign matches the prediction direction,
      - fundamental data (price, apy, emission) is present,
      - social data is available for hype-aligned signals.

    Confidence reflects input completeness.
    """
    signal_impact = signal_impact or {}
    subnet = subnet or {}

    impacts = signal_impact.get("impacts", []) or []
    non_neutral = [i for i in impacts if i.get("direction") in ("bullish", "bearish")]
    signal_score = min(len(non_neutral) / 6.0, 1.0)

    predicted_pct = float(prediction.get("predicted_pct", 0) or 0)
    chg_24h = float(subnet.get("price_change_24h", 0) or 0)
    direction_match = 0.5
    if predicted_pct > 0 and chg_24h >= 0:
        direction_match = 1.0
    elif predicted_pct < 0 and chg_24h < 0:
        direction_match = 1.0
    elif predicted_pct == 0:
        direction_match = 0.5
    else:
        direction_match = 0.3

    completeness = 0.0
    required = ["price", "apy", "emission"]
    present = sum(1 for k in required if subnet.get(k) not in (None, ""))
    completeness += present / len(required)
    if subnet.get("social_mentions") is not None:
        completeness += 0.25
    completeness = min(completeness, 1.0)

    score = _clamp(0.4 + 0.35 * signal_score + 0.15 * direction_match + 0.1 * completeness)
    confidence = _clamp(0.5 + 0.3 * completeness + 0.2 * signal_score)
    return {"score": round(score, 4), "confidence": round(confidence, 4)}
