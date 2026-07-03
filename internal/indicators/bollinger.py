"""Bollinger Bands computation."""
from typing import Any, Dict, List


def compute_bollinger(
    candles: List[Dict[str, Any]],
    period: int = 20,
    num_std: float = 2.0,
) -> Dict[str, Any]:
    """
    Compute Bollinger Bands from OHLCV candles.

    Returns upper, middle, lower bands, width, and signal flags.
    """
    if len(candles) < period:
        return {
            "upper": 0.0,
            "middle": 0.0,
            "lower": 0.0,
            "width": 0.0,
            "overbought": False,
            "oversold": False,
            "neutral": True,
        }

    closes = [c["close"] for c in candles]
    window = closes[-period:]
    mid = sum(window) / period
    variance = sum((x - mid) ** 2 for x in window) / period
    sd = variance ** 0.5
    upper = mid + num_std * sd
    lower = mid - num_std * sd
    price = closes[-1]

    return {
        "upper": round(upper, 6),
        "middle": round(mid, 6),
        "lower": round(lower, 6),
        "width": round(upper - lower, 6),
        "overbought": price > upper,
        "oversold": price < lower,
        "neutral": lower <= price <= upper,
    }