"""Scheduler hook for forward chain price recorder (worker, flag-gated)."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from internal.chain_client import _metric_endpoint, rate_limited_until
from internal.chain_price import config as cfg
from internal.chain_price.reader import get_shared_reader, reset_shared_reader
from internal.job_scheduler import cancel_job, schedule_interval_seconds

logger = logging.getLogger(__name__)

JOB_ID = "chain-price-forward-record"
PRUNE_JOB_ID = "chain-price-hourly-prune"
_active = False


def _tick() -> None:
    if not cfg.forward_record_enabled():
        stop_forward_recorder()
        return
    reader = get_shared_reader()
    from internal.chain_price.sampler import run_forward_sample

    result = run_forward_sample(reader)
    outcome = result.get("outcome")
    if outcome == "ok":
        logger.info(
            "chain price forward sample ok block=%s provider=%s samples=%s",
            result.get("block"),
            result.get("provider_served", result.get("provider")),
            result.get("samples_written"),
        )
    elif outcome == "disk_low":
        logger.debug("chain price forward sample skipped: disk_low")
    else:
        logger.warning("chain price forward sample: %s", result)


def _prune_tick() -> None:
    from internal.chain_price import db as price_db

    if not cfg.forward_record_enabled():
        return
    try:
        stats = price_db.run_hourly_prune_job()
        if stats["deleted_samples"] or stats["deleted_blocks"]:
            logger.info("chain price hourly prune: %s", stats)
    except OSError as exc:
        logger.warning("chain price hourly prune failed: %s", exc)


def _start_delay_seconds() -> float:
    """Align first tick to 5-minute boundary + 30s anchor."""
    now = time.time()
    interval = cfg.TICK_INTERVAL_SECONDS
    anchor = cfg.TICK_ANCHOR_OFFSET_SECONDS
    boundary = (int(now) // interval) * interval + anchor
    delay = boundary - now
    if delay < 1:
        delay += interval
    return delay


def start_forward_recorder() -> Dict[str, Any]:
    global _active
    if not cfg.forward_record_enabled():
        return {"started": False, "reason": "disabled"}
    if _active:
        return {"started": False, "reason": "already running"}
    reset_shared_reader()
    delay = _start_delay_seconds()
    schedule_interval_seconds(
        JOB_ID,
        _tick,
        cfg.TICK_INTERVAL_SECONDS,
        start_delay_seconds=delay,
    )
    schedule_interval_seconds(
        PRUNE_JOB_ID,
        _prune_tick,
        3600,
        start_delay_seconds=60.0,
    )
    _active = True
    logger.info(
        "chain price forward recorder scheduled every %ss (first in %.0fs)",
        cfg.TICK_INTERVAL_SECONDS,
        delay,
    )
    return {"started": True, "interval_seconds": cfg.TICK_INTERVAL_SECONDS, "first_delay": delay}


def stop_forward_recorder() -> Dict[str, Any]:
    global _active
    cancel_job(JOB_ID)
    cancel_job(PRUNE_JOB_ID)
    was = _active
    _active = False
    reset_shared_reader()
    return {"stopped": was}


def recorder_state() -> Dict[str, Any]:
    reader = get_shared_reader()
    now = time.monotonic()
    providers: list[Dict[str, Any]] = []
    for label, endpoint in reader.provider_states():
        cooldown_remaining_s = 0.0
        if endpoint:
            until = rate_limited_until(endpoint)
            if until > now:
                cooldown_remaining_s = until - now
        hostname = _metric_endpoint(endpoint) if endpoint else None
        providers.append(
            {
                "label": label,
                "hostname": hostname,
                "cooldown_remaining_s": round(cooldown_remaining_s, 1),
            }
        )
    return {
        "enabled": cfg.forward_record_enabled(),
        "active": _active,
        "db_path": cfg.CHAIN_PRICE_DB_PATH,
        "providers": providers,
    }
