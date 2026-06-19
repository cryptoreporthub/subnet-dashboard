"""MACD computation: EMA(12) - EMA(26), signal = EMA(9) of MACD line."""

import os
from typing import Any, Dict, List

DEFAULT_FAST = int(os.environ.get("MACD_FAST", "12"))
DEFAULT_SLOW = int(os.environ.get("MACD_SLOW", "26"))
DEFAULT_SIGNAL = int(os.environ.get("MACD_SIGNAL", "9"))


def _ema(series: List[float], period: int) -> List[float]:
    """Compute exponential moving average."""
    if len(series) < period:
        return []
    multiplier = 2.0 / (period + 1)
    ema_values = [sum(series[:period]) / period]
    for value in series[period:]:
        ema_values.append((value - ema_values[-1]) * multiplier + ema_values[-1])
    return ema_values


def compute_macd(
    candles: List[Dict[str, Any]],
    fast: int = DEFAULT_FAST,
    slow: int = DEFAULT_SLOW,
    signal: int = DEFAULT_SIGNAL,
) -> Dict[str, Any]:
    """
    Compute MACD, signal line, histogram, and cross flags.

    Returns current values, previous histogram, and bullish/bearish cross flags.
    """
    if len(candles) < slow + signal:
        return {
            "macd_line": 0.0,
            "signal_line": 0.0,
            "histogram": 0.0,
            "histogram_prev": 0.0,
            "bullish_cross": False,
            "bearish_cross": False,
            "above_zero": False,
            "momentum_increasing": False,
        }

    closes = [c["close"] for c in candles]
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)

    # Align series: ema_fast starts at index fast-1, ema_slow at slow-1.
    offset = slow - fast
    macd_line = [ema_fast[i + offset] - ema_slow[i] for i in range(len(ema_slow))]
    signal_line = _ema(macd_line, signal)

    # Align histogram with signal line.
    histogram = [macd_line[i + (len(macd_line) - len(signal_line))] - signal_line[i] for i in range(len(signal_line))]

    if not histogram:
        return {
            "macd_line": 0.0,
            "signal_line": 0.0,
            "histogram": 0.0,
            "histogram_prev": 0.0,
            "bullish_cross": False,
            "bearish_cross": False,
            "above_zero": False,
            "momentum_increasing": False,
        }

    current_hist = histogram[-1]
    previous_hist = histogram[-2] if len(histogram) > 1 else current_hist
    current_macd = macd_line[-1]

    bullish_cross = previous_hist < 0 <= current_hist
    bearish_cross = previous_hist > 0 >= current_hist

    return {
        "macd_line": round(current_macd, 6),
        "signal_line": round(signal_line[-1], 6),
        "histogram": round(current_hist, 6),
        "histogram_prev": round(previous_hist, 6),
        "bullish_cross": bullish_cross,
        "bearish_cross": bearish_cross,
        "above_zero": current_macd > 0,
        "momentum_increasing": current_hist > previous_hist,
    }
