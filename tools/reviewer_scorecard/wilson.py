"""Wilson score 97.5% one-sided lower limit (z = 1.96)."""

from __future__ import annotations

import math

Z_DEFAULT = 1.96


def wilson_lower_bound(successes: int, n: int, z: float = Z_DEFAULT) -> float | None:
    """Return Wilson LB for successes of n trials, or None when n == 0."""
    if n < 0 or successes < 0 or successes > n:
        raise ValueError("invalid successes/n")
    if n == 0:
        return None
    p_hat = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = p_hat + z2 / (2.0 * n)
    margin = z * math.sqrt(p_hat * (1.0 - p_hat) / n + z2 / (4.0 * n * n))
    return (center - margin) / denom


def round_metric(value: float | None, places: int = 6) -> float | None:
    if value is None:
        return None
    return round(value, places)
