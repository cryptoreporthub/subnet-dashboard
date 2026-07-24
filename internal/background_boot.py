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


def _start_pump_ladder() -> None:
    def _run() -> None:
        from internal.pump.scheduler import ensure_pump_ladder_scheduler

        ensure_pump_ladder_scheduler(immediate=True)
        logger.info("pump ladder scheduler started")

    defer_boot("pump-ladder-scheduler", _run)


def _start_resolver() -> None:
    def _run() -> None:
        from internal.council.resolver_scheduler import start_prediction_resolver_scheduler

        immediate = os.environ.get("RESOLVER_BOOT_IMMEDIATE", "off").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        start_prediction_resolver_scheduler(immediate=immediate)
        logger.info("prediction resolver scheduler started")
        try:
            from internal.learning.pump_lead_recover import recover_overdue_pump_leads

            summary = recover_overdue_pump_leads(dry_run=False)
            logger.info("pump_lead recover on boot: %s", summary)
        except Exception as exc:
            logger.warning("pump_lead recover boot failed: %s", exc)

    defer_boot("prediction-resolver", _run, delay=max(BOOT_DEFER_SECONDS + 10, 15))


def _start_whale_warm_scheduler() -> None:
    def _tick() -> None:
        try:
            from internal.pump.taostats_overlay import active_ladder_netuids
            from internal.whales.warm import ensure_whale_ledger_warm

            candidates = list(active_ladder_netuids())
            if not candidates:
                candidates = [64, 6, 2, 3, 7, 10, 18, 52, 97, 1]
            ensure_whale_ledger_warm(candidates)
        except Exception as exc:
            logger.warning("whale warm tick failed: %s", exc)

    try:
        minutes = int(os.environ.get("WHALE_LEDGER_WARM_INTERVAL_MINUTES", "20"))
    except ValueError:
        minutes = 20
    minutes = max(5, min(minutes, 120))

    def _run() -> None:
        from internal.job_scheduler import schedule_interval_seconds

        schedule_interval_seconds(
            "whale-ledger-warm",
            _tick,
            minutes * 60,
            start_delay_seconds=max(BOOT_DEFER_SECONDS + 30, 60),
        )
        logger.info("whale ledger warm scheduler every %s min", minutes)

    defer_boot("whale-warm-scheduler", _run, delay=max(BOOT_DEFER_SECONDS, 5))


def start_background_workers(*, heavy: Optional[bool] = None) -> None:
    """Start background schedulers.

    * **essential** (default on web with ``BACKGROUND_ON_WEB=essential``): pump
      ladder, resolver, whale warm, registry freshness — no live-subnet wedge.
    * **heavy** (worker or ``BACKGROUND_ON_WEB=on``): also live subnets, feed,
      message-intel listeners.
    """
    from internal.run_mode import background_heavy_on_web, is_worker_mode

    if heavy is None:
        heavy = is_worker_mode() or background_heavy_on_web()

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

    _start_pump_ladder()
    _start_resolver()
    _start_whale_warm_scheduler()

    if not heavy:
        logger.info("background workers: essential mode (heavy feeds skipped)")
        return

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
        from internal.pump.scheduler import stop_pump_ladder_scheduler

        stop_pump_ladder_scheduler()
    except Exception:
        pass
    try:
        from internal.job_scheduler import cancel_job, shutdown_background_scheduler

        cancel_job("whale-ledger-warm")
        shutdown_background_scheduler()
    except Exception:
        pass
