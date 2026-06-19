"""Relative Strength Index (RSI) computation."""

from typing import Optional, Sequence

import pandas as pd


def compute_rsi(prices, period: int = 14) -> Optional[float]:
    """Compute RSI for a price series using Wilder's smoothing.

    Args:
        prices: A list, pandas Series, or array-like of prices.
        period: Look-back window for RSI.

    Returns:
        RSI in the range 0-100, or None if not enough data.
    """
    series = pd.Series(prices) if not isinstance(prices, pd.Series) else prices
    if len(series) < period + 1:
        return None

    delta = series.diff().iloc[1:]
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)

    avg_gain = gain.iloc[:period].mean()
    avg_loss = loss.iloc[:period].mean()

    for i in range(period, len(gain)):
        avg_gain = (avg_gain * (period - 1) + gain.iloc[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss.iloc[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)
