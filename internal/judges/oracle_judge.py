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


def _source_alignment(prediction: Dict[str, Any], predicted_pct: float) -> float:
    """Boost when alert source matches prediction sign; penalize contradictions."""
    source = str(prediction.get("signal_source") or "").upper()
    if not source or source == "NEUTRAL":
        return 0.5
    bullish = predicted_pct > 0
    bearish = predicted_pct < 0
    if source in ("HOT", "BUY") and bullish:
        return 1.0
    if source in ("SELL ALERT", "SELL") and bearish:
        return 1.0
    if source in ("HOT", "BUY") and bearish:
        return 0.2
    if source in ("SELL ALERT", "SELL") and bullish:
        return 0.2
    return 0.5


def evaluate(
    prediction: Dict[str, Any],
    signal_impact: Optional[Dict[str, Any]] = None,
    subnet: Optional[Dict[str, Any]] = None,
) -> Dict[str, float]:
    """Return Oracle score and confidence for a prediction."""
    signal_impact = signal_impact or {}
    subnet = subnet or {}

    impacts = signal_impact.get("impacts", []) or []
    non_neutral = [i for i in impacts if i.get("direction") in ("bullish", "bearish")]
    signal_score = min(len(non_neutral) / 5.0, 1.0)
    if signal_impact.get("dominant") in ("HOT", "SELL ALERT"):
        signal_score = min(1.0, signal_score + 0.15)

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
        direction_match = 0.25
    direction_match = 0.6 * direction_match + 0.4 * _source_alignment(prediction, predicted_pct)

    completeness = 0.0
    required = ["price", "apy", "emission"]
    present = sum(1 for k in required if subnet.get(k) not in (None, ""))
    completeness += present / len(required)
    if subnet.get("social_mentions") is not None:
        completeness += 0.25
    if subnet.get("volume") not in (None, "", 0):
        completeness += 0.15
    completeness = min(completeness, 1.0)

    score = _clamp(
        0.32
        + 0.32 * signal_score
        + 0.22 * direction_match
        + 0.14 * completeness
    )
    confidence = _clamp(0.45 + 0.32 * completeness + 0.23 * signal_score)
    return {"score": round(score, 4), "confidence": round(confidence, 4)}
