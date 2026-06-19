"""MACD (Moving Average Convergence Divergence) computation."""

from typing import Dict, Optional, Sequence, Union

import pandas as pd


def compute_macd(
    prices,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Optional[Dict[str, Union[float, str]]]:
    """Compute MACD line, signal line, histogram, and trend direction.

    Args:
        prices: A list or pandas Series of prices.
        fast: Fast EMA span.
        slow: Slow EMA span.
        signal: Signal EMA span.

    Returns:
        Dict with keys: macd, signal, histogram, trend. None if too little data.
    """
    series = pd.Series(prices) if not isinstance(prices, pd.Series) else prices
    min_len = max(slow, signal) + 1
    if len(series) < min_len:
        return None

    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    return {
        "macd": round(float(macd_line.iloc[-1]), 6),
        "signal": round(float(signal_line.iloc[-1]), 6),
        "histogram": round(float(histogram.iloc[-1]), 6),
        "trend": "bullish" if macd_line.iloc[-1] > signal_line.iloc[-1] else "bearish",
    }
