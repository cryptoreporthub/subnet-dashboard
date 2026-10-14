"""Historical chain price backfill (#1395 Step 3)."""

from __future__ import annotations

import logging
import os
import time
from typing import List, Optional

from internal.chain_price import db as price_db
from internal.chain_price.block_resolve import resolve_block_at
from internal.chain_price.reader import ChainReader
from internal.chain_price.sampler import _KIND_BACKFILL, sample_at_block_hash

logger = logging.getLogger(__name__)

HOUR_MS = 3_600_000
_SEARCH_MODES = frozenset({"stepped", "bracketed"})
_DEFAULT_SLEEP_S = 1.5


def backfill_sleep_seconds() -> float:
    raw = os.environ.get("CHAIN_PRICE_BACKFILL_SLEEP_S", str(_DEFAULT_SLEEP_S))
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning("invalid CHAIN_PRICE_BACKFILL_SLEEP_S=%r; using %s", raw, _DEFAULT_SLEEP_S)
        return _DEFAULT_SLEEP_S


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


def backfill_bucket(
    reader: ChainReader,
    bucket_ts_ms: int,
    *,
    db_path: Optional[str] = None,
    dry_run: bool = False,
    gecko_fallback: bool = False,
    search: str = "bracketed",
) -> dict:
    """Resolve one hourly bucket and sample chain prices at the pinned block."""
    if search not in _SEARCH_MODES:
        raise ValueError(f"unknown search mode: {search!r}")
    if gecko_fallback:
        return {
            "outcome": "gecko_fallback_unavailable",
            "bucket_ts_ms": bucket_ts_ms,
            "error": "Gecko pool fallback requires #1397 (currency=token); not enabled",
        }

    db_file = db_path
    try:
        price_db.ensure_schema(db_path)
    except OSError as exc:
        return {
            "outcome": "db_unavailable",
            "bucket_ts_ms": bucket_ts_ms,
            "error": str(exc),
        }

    if price_db.hourly_bucket_has_chain_sample(bucket_ts_ms, path=db_path):
        return {
            "outcome": "skipped",
            "reason": "hourly_chain_sampled_exists",
            "bucket_ts_ms": bucket_ts_ms,
            "samples_written": 0,
        }

    anchors = price_db.load_anchor_blocks(bucket_ts_ms, HOUR_MS, path=db_path)
    hint = anchors[-1] if anchors else None
    target_ts_ms = bucket_ts_ms

    block, block_hash, resolve_outcome = resolve_block_at(
        reader,
        target_ts_ms,
        hint_block=hint,
        search=search,
        anchor_blocks=anchors,
    )
    if resolve_outcome != "ok" or block is None or not block_hash:
        return {
            "outcome": resolve_outcome or "invalid",
            "bucket_ts_ms": bucket_ts_ms,
            "block": block,
            "block_hash": block_hash,
            "samples_written": 0,
        }

    if dry_run:
        return {
            "outcome": "dry_run",
            "bucket_ts_ms": bucket_ts_ms,
            "block": block,
            "block_hash": block_hash,
            "search": search,
            "samples_written": 0,
        }

    sample = sample_at_block_hash(
        reader,
        block_hash,
        block,
        write=True,
        kind=_KIND_BACKFILL,
        db_path=db_path,
        bucket_ts_override=bucket_ts_ms,
        bump_schema_miss_on_error=False,
    )
    return {
        "bucket_ts_ms": bucket_ts_ms,
        "search": search,
        "fallback": None,
        **sample,
    }


def run_backfill_dry_run(
    bucket_ts_ms: int,
    *,
    search: str = "bracketed",
) -> dict:
    """Plan-only helper when no reader is available (CLI bucket preview)."""
    if search not in _SEARCH_MODES:
        raise ValueError(f"unknown search mode: {search!r}")
    return {
        "outcome": "dry_run",
        "bucket_ts_ms": bucket_ts_ms,
        "search": search,
        "note": "use live backfill without --dry-run to resolve and sample",
    }
