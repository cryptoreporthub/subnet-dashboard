"""
Oracle Judge — evaluates signals for truthfulness / evidentiary quality.

Scores align prediction evidence with observable subnet metrics and snapshots.
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


def _direction_alignment(
    predicted_pct: float,
    subnet: Dict[str, Any],
    prediction: Dict[str, Any],
) -> float:
    chg_24h = float(subnet.get("price_change_24h", 0) or 0)
    chg_7d = float(subnet.get("price_change_7d", chg_24h) or 0)
    if predicted_pct > 0:
        match_24 = 1.0 if chg_24h >= 0 else 0.25
        match_7d = 1.0 if chg_7d >= -1.0 else 0.3
    elif predicted_pct < 0:
        match_24 = 1.0 if chg_24h <= 0 else 0.25
        match_7d = 1.0 if chg_7d <= 1.0 else 0.3
    else:
        match_24 = match_7d = 0.5
    direction_match = 0.45 * match_24 + 0.35 * match_7d + 0.2 * _source_alignment(prediction, predicted_pct)
    if subnet.get("yield_trap") and predicted_pct > 0:
        direction_match *= 0.75
    if str(prediction.get("magnitude_source") or "") == "signal_impact":
        direction_match = min(1.0, direction_match + 0.08)
    return direction_match


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
    try:
        net_pred = float(signal_impact.get("net_predicted_pct") or prediction.get("predicted_pct") or 0)
    except (TypeError, ValueError):
        net_pred = 0.0
    if net_pred != 0 and impacts:
        aligned = sum(
            1
            for item in impacts
            if (item.get("direction") == "bullish" and net_pred > 0)
            or (item.get("direction") == "bearish" and net_pred < 0)
        )
        signal_score = min(1.0, signal_score + 0.1 * aligned)

    predicted_pct = float(prediction.get("predicted_pct", 0) or 0)
    direction_match = _direction_alignment(predicted_pct, subnet, prediction)

    completeness = 0.0
    required = ["price", "apy", "emission"]
    present = sum(1 for k in required if subnet.get(k) not in (None, ""))
    completeness += present / len(required)
    if subnet.get("social_mentions") is not None:
        completeness += 0.2
    if subnet.get("volume") not in (None, "", 0):
        completeness += 0.15
    if subnet.get("price_change_7d") is not None:
        completeness += 0.1
    completeness = min(completeness, 1.0)

    score = _clamp(0.28 + 0.34 * signal_score + 0.24 * direction_match + 0.14 * completeness)
    confidence = _clamp(0.42 + 0.34 * completeness + 0.24 * signal_score)
    return {"score": round(score, 4), "confidence": round(confidence, 4)}


if __name__ == "__main__":
    out = evaluate(
        {"predicted_pct": 3.0, "signal_source": "HOT", "magnitude_source": "signal_impact"},
        signal_impact={"impacts": [{"direction": "bullish", "magnitude_pct": 3.0}], "net_predicted_pct": 3.0},
        subnet={"price": 1.0, "apy": 0.2, "emission": 1.0, "price_change_24h": 2.0, "price_change_7d": 5.0},
    )
    assert out["score"] >= 0.55
    print("oracle_judge self-check ok")
