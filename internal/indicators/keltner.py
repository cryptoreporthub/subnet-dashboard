"""Keltner Channels computation."""
from typing import Any, Dict, List


def _ema(series: List[float], period: int) -> float:
    if not series:
        return 0.0
    k = 2.0 / (period + 1)
    ema = series[0]
    for v in series[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def compute_keltner(
    candles: List[Dict[str, Any]],
    period: int = 20,
    mult: float = 2.0,
) -> Dict[str, Any]:
    """
    Compute Keltner Channels from OHLCV candles.

    Returns upper, middle (EMA), lower bands and signal flags.
    """
    if len(candles) < period:
        return {
            "upper": 0.0,
            "middle": 0.0,
            "lower": 0.0,
            "overbought": False,
            "oversold": False,
            "neutral": True,
        }

    closes = [c["close"] for c in candles]
    ema_val = _ema(closes[-period * 3:], period)

    trs = []
    for i in range(1, min(len(candles), period * 2)):
        high = candles[-i]["high"]
        low = candles[-i]["low"]
        prev_close = candles[-i - 1]["close"]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    atr = sum(trs) / len(trs) if trs else 0.0

    upper = ema_val + mult * atr
    lower = ema_val - mult * atr
    price = closes[-1]

    return {
        "upper": round(upper, 6),
        "middle": round(ema_val, 6),
        "lower": round(lower, 6),
        "overbought": price > upper,
        "oversold": price < lower,
        "neutral": lower <= price <= upper,
    }