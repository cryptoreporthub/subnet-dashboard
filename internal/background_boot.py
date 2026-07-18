"""Background schedulers shared by server lifespan (combined) and internal.worker."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

BOOT_DEFER_SECONDS = int(os.environ.get("BOOT_DEFER_SECONDS", "45"))


def defer_boot(name: str, target: Callable[[], None], delay: Optional[int] = None) -> None:
    """ponytail: delay heavy boot threads so /health wins the first minute on Fly."""
    wait = BOOT_DEFER_SECONDS if delay is None else delay

    def _run() -> None:
        if wait > 0:
            time.sleep(wait)
        try:
            target()
        except Exception as exc:
            logger.warning("%s boot task failed: %s", name, exc)

    threading.Thread(target=_run, daemon=True, name=name).start()


def start_background_workers() -> None:
    """Start resolver, freshness sync, live feed, and optional listeners."""
    try:
        from internal.freshness import start_background_sync

        boot_sync = os.environ.get("BOOT_BACKGROUND_SYNC_IMMEDIATE", "off").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        start_background_sync(immediate=boot_sync)
        logger.info("Registry freshness background sync started")
    except Exception as exc:
        logger.warning("Registry freshness sync failed to start: %s", exc)
    try:
        from internal.live_subnets import get_live_subnets

        defer_boot("live-subnets-boot", get_live_subnets)
        logger.info("Live subnets sync scheduled (deferred %ss)", BOOT_DEFER_SECONDS)
    except Exception as exc:
        logger.warning("Live subnets sync failed to start: %s", exc)
    try:
        from internal.subnets.feed import warm_subnet_feed

        defer_boot("subnet-feed-warmup", warm_subnet_feed)
        logger.info("Subnet feed warmup deferred %ss", BOOT_DEFER_SECONDS)
    except Exception as exc:
        logger.warning("Subnet feed warmup failed to start: %s", exc)
    try:
        from internal.council.resolver_scheduler import start_prediction_resolver_scheduler

        resolver_immediate = os.environ.get("RESOLVER_BOOT_IMMEDIATE", "off").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        start_prediction_resolver_scheduler(immediate=resolver_immediate)
        logger.info("Prediction resolver scheduler started")
    except Exception as exc:
        logger.warning("Prediction resolver scheduler failed to start: %s", exc)
    try:
        from internal.message_intel.listener_service import start_message_intel_listeners

        start_message_intel_listeners()
    except Exception as exc:
        logger.warning("Message-intel listeners failed to start: %s", exc)


def stop_background_workers() -> None:
    try:
        from internal.message_intel.listener_service import stop_message_intel_listeners

        stop_message_intel_listeners()
    except Exception:
        pass
    try:
        from internal.council.resolver_scheduler import stop_prediction_resolver_scheduler

        stop_prediction_resolver_scheduler()
    except Exception:
        pass
    try:
        from internal.job_scheduler import shutdown_background_scheduler

        shutdown_background_scheduler()
    except Exception:
        pass
