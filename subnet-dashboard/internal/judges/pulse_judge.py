"""
Pulse Judge — measures momentum / energy behind a prediction.

Pulse scores are driven by the strength and recency of price movement, volume,
and the magnitude of the strongest signal impact. It rewards aligned, energetic
setups and penalizes low-momentum contradictions.
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
    """Return Pulse score and confidence for a prediction.

    Score is higher when:
      - the 24h price change magnitude is meaningful but not extreme,
      - volume is present (relative to a sane subnet baseline),
      - the strongest signal impact aligns with the prediction direction,
      - the predicted magnitude is proportional to observed momentum.

    Confidence reflects data freshness (assumed fresh when volume exists).
    """
    signal_impact = signal_impact or {}
    subnet = subnet or {}

    chg = float(subnet.get("price_change_24h", 0) or 0)
    momentum_score = _clamp(abs(chg) / 10.0)
    if abs(chg) > 50:
        momentum_score = 0.6  # extreme moves are noisy, not reliable

    volume = float(subnet.get("volume", 0) or 0)
    volume_score = _clamp(volume / 1_000_000.0)

    impacts = signal_impact.get("impacts", []) or []
    if impacts:
        strongest = max(impacts, key=lambda i: abs(i.get("magnitude_pct", 0) or 0))
        strongest_mag = abs(strongest.get("magnitude_pct", 0) or 0)
        impact_score = _clamp(strongest_mag / 5.0)
        strongest_dir = strongest.get("direction", "neutral")
        pred_direction = prediction.get("direction", "up")
        target = "bullish" if pred_direction == "up" else "bearish" if pred_direction == "down" else "neutral"
        aligned = strongest_dir == target
    else:
        impact_score = 0.0
        aligned = False

    predicted_pct = abs(float(prediction.get("predicted_pct", 0) or 0))
    proportion_score = 0.5
    if chg != 0:
        ratio = predicted_pct / max(abs(chg), 0.1)
        proportion_score = _clamp(1.0 - abs(ratio - 1.0))

    alignment_bonus = 0.15 if aligned else 0.0
    score = _clamp(
        0.3
        + 0.25 * momentum_score
        + 0.15 * volume_score
        + 0.2 * impact_score
        + 0.1 * proportion_score
        + alignment_bonus
    )
    confidence = _clamp(0.45 + 0.35 * volume_score + 0.2 * momentum_score)
    return {"score": round(score, 4), "confidence": round(confidence, 4)}
