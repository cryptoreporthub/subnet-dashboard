"""Momentum indicators: Stochastic Oscillator, Williams %R, Rate of Change."""

from typing import Any, Dict, List


def _stochastic_k(candles: List[Dict[str, Any]], period: int) -> List[float]:
    """Raw %K series for the stochastic oscillator."""
    ks: List[float] = []
    for i in range(period - 1, len(candles)):
        window = candles[i - period + 1 : i + 1]
        highs = [c["high"] for c in window]
        lows = [c["low"] for c in window]
        close = candles[i]["close"]
        highest = max(highs)
        lowest = min(lows)
        range_ = highest - lowest
        if range_ == 0:
            ks.append(50.0)
        else:
            ks.append(100.0 * (close - lowest) / range_)
    return ks


def _sma(values: List[float], period: int) -> List[float]:
    if len(values) < period:
        return []
    return [sum(values[i - period + 1 : i + 1]) / period for i in range(period - 1, len(values))]


def _williams_r(candles: List[Dict[str, Any]], period: int) -> List[float]:
    """Williams %R series."""
    values: List[float] = []
    for i in range(period - 1, len(candles)):
        window = candles[i - period + 1 : i + 1]
        highest = max(c["high"] for c in window)
        lowest = min(c["low"] for c in window)
        close = candles[i]["close"]
        range_ = highest - lowest
        if range_ == 0:
            values.append(-50.0)
        else:
            values.append(-100.0 * (highest - close) / range_)
    return values


def _roc(closes: List[float], period: int) -> List[float]:
    """Rate of change series."""
    return [((closes[i] - closes[i - period]) / closes[i - period]) * 100.0 for i in range(period, len(closes))]


def compute_momentum(
    candles: List[Dict[str, Any]],
    stoch_period: int = 14,
    stoch_d: int = 3,
    williams_period: int = 14,
    roc_period: int = 10,
) -> Dict[str, Any]:
    """
    Compute Stochastic %K/%D, Williams %R, and Rate of Change.

    Returns current and previous values plus trend flags.
    """
    if len(candles) < max(stoch_period + stoch_d, williams_period, roc_period) + 1:
        return {
            "stochastic_k": 50.0,
            "stochastic_k_prev": 50.0,
            "stochastic_d": 50.0,
            "stochastic_d_prev": 50.0,
            "stochastic_oversold": False,
            "stochastic_overbought": False,
            "williams_r": -50.0,
            "williams_r_prev": -50.0,
            "williams_oversold": False,
            "williams_overbought": False,
            "roc": 0.0,
            "roc_prev": 0.0,
            "roc_increasing": False,
            "roc_crossed_zero": False,
        }

    ks = _stochastic_k(candles, stoch_period)
    ds = _sma(ks, stoch_d)

    williams = _williams_r(candles, williams_period)
    closes = [c["close"] for c in candles]
    roc_values = _roc(closes, roc_period)

    def _trend(current: float, previous: float) -> str:
        if current > previous + 1e-9:
            return "rising"
        if current < previous - 1e-9:
            return "falling"
        return "flat"

    k_current = ks[-1] if ks else 50.0
    k_prev = ks[-2] if len(ks) > 1 else k_current
    d_current = ds[-1] if ds else k_current
    d_prev = ds[-2] if len(ds) > 1 else d_current

    w_current = williams[-1] if williams else -50.0
    w_prev = williams[-2] if len(williams) > 1 else w_current

    roc_current = roc_values[-1] if roc_values else 0.0
    roc_prev = roc_values[-2] if len(roc_values) > 1 else roc_current

    return {
        "stochastic_k": round(k_current, 4),
        "stochastic_k_prev": round(k_prev, 4),
        "stochastic_d": round(d_current, 4),
        "stochastic_d_prev": round(d_prev, 4),
        "stochastic_oversold": k_current < 20.0,
        "stochastic_overbought": k_current > 80.0,
        "stochastic_trend": _trend(k_current, k_prev),
        "williams_r": round(w_current, 4),
        "williams_r_prev": round(w_prev, 4),
        "williams_oversold": w_current < -80.0,
        "williams_overbought": w_current > -20.0,
        "williams_trend": _trend(w_current, w_prev),
        "roc": round(roc_current, 4),
        "roc_prev": round(roc_prev, 4),
        "roc_increasing": roc_current > roc_prev,
        "roc_crossed_zero": (roc_prev < 0 <= roc_current) or (roc_prev > 0 >= roc_current),
    }
