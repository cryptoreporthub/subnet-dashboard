"""Momentum / Rate-of-Change computation."""

from typing import Optional, Sequence


def compute_momentum(prices, period: int = 10) -> Optional[float]:
    """Return the percentage change from ``period`` bars ago to the latest price.

    Returns:
        Momentum as a percentage, or None if not enough data.
    """
    if len(prices) < period + 1:
        return None
    previous = float(prices[-period])
    if previous == 0:
        return None
    return round((float(prices[-1]) - previous) / previous * 100, 4)
