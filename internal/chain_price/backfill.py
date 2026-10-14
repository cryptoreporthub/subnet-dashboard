"""Historical chain price backfill planning (#1395 Step 3)."""

from __future__ import annotations

import time
from typing import List, Optional

HOUR_MS = 3_600_000


def plan_hourly_bucket_ts_ms(
    end_ms: Optional[int] = None,
    *,
    days: int = 30,
) -> List[int]:
    """UTC hour bucket starts from ``end_ms`` (default now), going back ``days`` inclusive."""
    if days < 1:
        return []
    if end_ms is None:
        end_ms = int(time.time() * 1000)
    end_hour = (end_ms // HOUR_MS) * HOUR_MS
    start_hour = end_hour - (days * 24 - 1) * HOUR_MS
    buckets: List[int] = []
    t = start_hour
    while t <= end_hour:
        buckets.append(t)
        t += HOUR_MS
    return buckets


def run_backfill_dry_run(
    bucket_ts_ms: int,
    *,
    search: str = "bracketed",
) -> dict:
    """Smoke helper: report what a bucket would do without RPC or DB writes."""
    return {
        "outcome": "dry_run",
        "bucket_ts_ms": bucket_ts_ms,
        "search": search,
    }
