"""RSI computation using Wilder's smoothing method."""

import os
from typing import Any, Dict, List

DEFAULT_PERIOD = int(os.environ.get("RSI_PERIOD", "14"))


def _changes(closes: List[float]) -> List[float]:
    return [closes[i] - closes[i - 1] for i in range(1, len(closes))]


def _wilder_smoothing(values: List[float], period: int) -> List[float]:
    """Apply Wilder's smoothing: first value is SMA, then RMA."""
    if len(values) < period:
        return []
    smoothed = [sum(values[:period]) / period]
    for v in values[period:]:
        smoothed.append((smoothed[-1] * (period - 1) + v) / period)
    return smoothed


def compute_rsi(candles: List[Dict[str, Any]], period: int = DEFAULT_PERIOD) -> Dict[str, Any]:
    """
    Compute RSI using Wilder's smoothing method.

    Returns current RSI, previous RSI, threshold flags, trend, and full series.
    """
    if len(candles) < period + 1:
        return {
            "rsi": 50.0,
            "rsi_prev": 50.0,
            "overbought": False,
            "oversold": False,
            "neutral": True,
            "trend": "flat",
            "series": [],
        }

    closes = [c["close"] for c in candles]
    changes = _changes(closes)

    gains = [max(c, 0.0) for c in changes]
    losses = [max(-c, 0.0) for c in changes]

    avg_gains = _wilder_smoothing(gains, period)
    avg_losses = _wilder_smoothing(losses, period)

    series: List[float] = []
    for ag, al in zip(avg_gains, avg_losses):
        if al == 0:
            rsi = 100.0
        else:
            rs = ag / al
            rsi = 100.0 - (100.0 / (1.0 + rs))
        series.append(round(rsi, 4))

    if not series:
        return {
            "rsi": 50.0,
            "rsi_prev": 50.0,
            "overbought": False,
            "oversold": False,
            "neutral": True,
            "trend": "flat",
            "series": [],
        }

    current = series[-1]
    previous = series[-2] if len(series) > 1 else current

    if current > previous + 1e-9:
        trend = "rising"
    elif current < previous - 1e-9:
        trend = "falling"
    else:
        trend = "flat"

    return {
        "rsi": round(current, 4),
        "rsi_prev": round(previous, 4),
        "overbought": current > 70.0,
        "oversold": current < 30.0,
        "neutral": 30.0 <= current <= 70.0,
        "trend": trend,
        "series": series,
    }
