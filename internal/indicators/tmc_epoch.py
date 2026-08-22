"""Named TMC data-epoch source for daily-pick score caching.

Epoch key: ``min(subnets.cached_at, candles.cached_at)`` from
``price_fetcher``'s module-level TMC caches — the same payloads
``tmc_singleflight`` serializes refresh for.  Both timestamps advance
together on every single-flight refresh, so the minimum cannot drift
ahead of actual data freshness for either endpoint.
"""

from __future__ import annotations

import os
import time
from typing import Tuple

from internal.indicators import price_fetcher as _pf

# Independent staleness guard: if the epoch source is older than this,
# callers must bypass the score cache (see pick_score_cache.begin).
DEFAULT_MAX_EPOCH_AGE_SECONDS = int(
    os.environ.get("DPICK_CACHE_MAX_EPOCH_AGE_SECONDS", "120")
)


def tmc_data_epoch_unix() -> float:
    """Unix timestamp of the current TMC data epoch (0 when cold)."""
    subnets_at = float(_pf._tmc_subnets_cache.get("cached_at") or 0.0)
    candles_at = float(_pf._tmc_candles_cache.get("cached_at") or 0.0)
    if subnets_at <= 0.0 or candles_at <= 0.0:
        return 0.0
    return min(subnets_at, candles_at)


def epoch_age_seconds(now: float | None = None) -> float:
    """Seconds since the TMC data epoch; inf when cold."""
    epoch = tmc_data_epoch_unix()
    if epoch <= 0.0:
        return float("inf")
    return float(now if now is not None else time.time()) - epoch


def is_epoch_stale(max_age_seconds: int | None = None) -> bool:
    """True when the epoch source is cold or older than *max_age_seconds*."""
    limit = DEFAULT_MAX_EPOCH_AGE_SECONDS if max_age_seconds is None else int(max_age_seconds)
    return epoch_age_seconds() > float(limit)
