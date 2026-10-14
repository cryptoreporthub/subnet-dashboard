"""Scheduler hook for forward chain price recorder (worker, flag-gated)."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from internal.chain_client import ChainClient
from internal.chain_price import config as cfg
from internal.job_scheduler import cancel_job, schedule_interval_seconds

logger = logging.getLogger(__name__)

JOB_ID = "chain-price-forward-record"
_active = False


def _tick() -> None:
    if not cfg.forward_record_enabled():
        stop_forward_recorder()
        return
    endpoint, provider = cfg.primary_rpc_endpoint()
    client = ChainClient(endpoint=endpoint)
    from internal.chain_price.sampler import run_forward_sample

    result = run_forward_sample(client)
    outcome = result.get("outcome")
    if outcome == "ok":
        logger.info(
            "chain price forward sample ok block=%s provider=%s samples=%s",
            result.get("block"),
            result.get("provider", provider),
            result.get("samples_written"),
        )
    elif outcome == "disk_low":
        logger.debug("chain price forward sample skipped: disk_low")
    else:
        logger.warning("chain price forward sample: %s", result)


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
    delay = _start_delay_seconds()
    schedule_interval_seconds(
        JOB_ID,
        _tick,
        cfg.TICK_INTERVAL_SECONDS,
        start_delay_seconds=delay,
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
    was = _active
    _active = False
    return {"stopped": was}


def recorder_state() -> Dict[str, Any]:
    return {
        "enabled": cfg.forward_record_enabled(),
        "active": _active,
        "db_path": cfg.CHAIN_PRICE_DB_PATH,
    }
