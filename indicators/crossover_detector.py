"""Crossover detectors for moving averages and MACD."""

from typing import Dict, List, Optional

import pandas as pd


def detect_sma_cross(
    prices,
    fast_span: int = 20,
    slow_span: int = 50,
) -> Optional[Dict]:
    """Detect golden/death cross of a fast SMA over a slow SMA.

    Returns:
        A dict describing the most recent cross, or None if no cross at the
        last bar.
    """
    series = pd.Series(prices) if not isinstance(prices, pd.Series) else prices
    if len(series) < slow_span + 2:
        return None

    fast_sma = series.rolling(window=fast_span).mean()
    slow_sma = series.rolling(window=slow_span).mean()

    prev_fast, prev_slow = fast_sma.iloc[-2], slow_sma.iloc[-2]
    curr_fast, curr_slow = fast_sma.iloc[-1], slow_sma.iloc[-1]

    if prev_fast <= prev_slow and curr_fast > curr_slow:
        return {
            "type": "golden_cross",
            "fast_span": fast_span,
            "slow_span": slow_span,
            "signal_type": "breakout",
        }
    if prev_fast >= prev_slow and curr_fast < curr_slow:
        return {
            "type": "death_cross",
            "fast_span": fast_span,
            "slow_span": slow_span,
            "signal_type": "breakout",
        }
    return None


def detect_macd_cross(macd_series, signal_series) -> Optional[Dict]:
    """Detect a bullish or bearish MACD signal-line cross.

    Args:
        macd_series: List or pandas Series of MACD line values.
        signal_series: List or pandas Series of signal-line values.

    Returns:
        A dict describing the last cross, or None.
    """
    macd = pd.Series(macd_series)
    signal = pd.Series(signal_series)
    if len(macd) < 2 or len(signal) < 2:
        return None

    prev_macd, prev_signal = macd.iloc[-2], signal.iloc[-2]
    curr_macd, curr_signal = macd.iloc[-1], signal.iloc[-1]

    if prev_macd <= prev_signal and curr_macd > curr_signal:
        return {"type": "macd_bullish_cross", "signal_type": "momentum"}
    if prev_macd >= prev_signal and curr_macd < curr_signal:
        return {"type": "macd_bearish_cross", "signal_type": "momentum"}
    return None


def detect_all_crossovers(
    prices, macd_series=None, signal_series=None
) -> List[Dict]:
    """Return all crossovers detected at the most recent bar."""
    crosses: List[Dict] = []
    sma_cross = detect_sma_cross(prices)
    if sma_cross:
        crosses.append(sma_cross)
    if macd_series is not None and signal_series is not None:
        macd_cross = detect_macd_cross(macd_series, signal_series)
        if macd_cross:
            crosses.append(macd_cross)
    return crosses
