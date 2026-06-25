"""Technical analysis utilities for signal aggregation and scoring."""

from typing import Any, Dict, List


def aggregate_technical_signals(indicator_state: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregate per-subnet indicator data into a technical opinion snapshot."""
    per_subnet = indicator_state.get("per_subnet", {})
    signals: List[Dict[str, Any]] = []
    for sid, data in per_subnet.items():
        rsi = data.get("rsi")
        macd_hist = data.get("macd_histogram")
        stoch_k = data.get("stochastic_k")
        active = data.get("active_signals", [])

        bullish = any("bullish" in s or "oversold" in s for s in active)
        bearish = any("bearish" in s or "overbought" in s for s in active)

        score = 0.5
        if bullish:
            score = 0.7 + min(0.25, len(active) * 0.05)
        if bearish:
            score = max(0.0, min(score, 0.5 - len(active) * 0.05))
        if macd_hist is not None:
            score += 0.05 if macd_hist > 0 else -0.05
        if stoch_k is not None:
            if stoch_k < 20:
                score += 0.05
            elif stoch_k > 80:
                score -= 0.05
        score = round(min(1.0, max(0.0, score)), 4)

        signals.append({
            "subnet_id": int(sid),
            "rsi": rsi,
            "macd_histogram": macd_hist,
            "stochastic_k": stoch_k,
            "active_signals": active,
            "aggregate_score": score,
            "bias": "bullish" if score > 0.6 else "bearish" if score < 0.4 else "neutral",
        })
    return {"signals": signals, "count": len(signals)}


def compute_technical_conviction(indicator_data: Dict[str, Any]) -> int:
    """Derive a conviction percentage (0-100) from per-subnet indicator data."""
    score = indicator_data.get("aggregate_score", 0.5)
    raw = int(round(score * 100))
    return max(0, min(100, raw))


def pick_rationale_from_indicators(sid: str, per_subnet: Dict[str, Any]) -> str:
    """Build a human-readable rationale string from indicator signals."""
    data = per_subnet.get(sid, {})
    active = data.get("active_signals", [])
    rsi = data.get("rsi")
    macd = data.get("macd_histogram")

    parts: List[str] = []
    if rsi is not None:
        parts.append(f"RSI at {rsi:.1f}")
    if macd is not None:
        parts.append(f"MACD histogram {'positive' if macd > 0 else 'negative'} ({macd:.4f})")
    if active:
        parts.append(f"signals: {', '.join(active[:3])}")
    return " | ".join(parts) if parts else "No technical signals available"