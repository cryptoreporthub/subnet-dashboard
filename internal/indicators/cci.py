"""Commodity Channel Index (CCI) computation."""
from typing import Any, Dict, List


def compute_cci(
    candles: List[Dict[str, Any]],
    period: int = 20,
) -> Dict[str, Any]:
    """
    Compute Commodity Channel Index from OHLCV candles.

    Returns CCI value and overbought/oversold flags.
    """
    if len(candles) < period:
        return {
            "cci": 0.0,
            "overbought": False,
            "oversold": False,
            "neutral": True,
        }

    typical = [(c["high"] + c["low"] + c["close"]) / 3.0 for c in candles]
    window = typical[-period:]
    sma_t = sum(window) / period
    mean_dev = sum(abs(x - sma_t) for x in window) / period
    if mean_dev == 0:
        cci = 0.0
    else:
        cci = (typical[-1] - sma_t) / (0.015 * mean_dev)

    return {
        "cci": round(cci, 4),
        "overbought": cci > 100.0,
        "oversold": cci < -100.0,
        "neutral": -100.0 <= cci <= 100.0,
    }