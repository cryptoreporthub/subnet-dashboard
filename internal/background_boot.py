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


def _pump_boot_immediate() -> bool:
    flag = os.environ.get("PUMP_LADDER_BOOT_IMMEDIATE", "off").strip().lower()
    return flag in ("1", "true", "yes", "on")


def _pump_inline_defer_seconds() -> int:
    try:
        return max(60, int(os.environ.get("PUMP_LADDER_INLINE_DEFER_SECONDS", "300")))
    except ValueError:
        return 300


def _pump_inline_scheduler_enabled() -> bool:
    flag = os.environ.get("PUMP_LADDER_INLINE_SCHEDULER", "off").strip().lower()
    return flag in ("1", "true", "yes", "on")


def _start_pump_ladder() -> None:
    from internal.run_mode import inline_worker_expected

    if inline_worker_expected() and not _pump_inline_scheduler_enabled():
        logger.info(
            "pump ladder scheduler skipped on inline worker (PUMP_LADDER_INLINE_SCHEDULER=off)"
        )
        return

    def _run() -> None:
        from internal.pump.scheduler import ensure_pump_ladder_scheduler

        ensure_pump_ladder_scheduler(immediate=_pump_boot_immediate())
        logger.info("pump ladder scheduler started (immediate=%s)", _pump_boot_immediate())

    from internal.run_mode import inline_worker_expected

    # ponytail: on split VM, defer pump scan until HTTP has been stable ~5 min — 120s
    # wedge was killing the only Fly machine (0-byte /health timeouts).
    delay = BOOT_DEFER_SECONDS
    if inline_worker_expected():
        delay = _pump_inline_defer_seconds()
    defer_boot("pump-ladder-scheduler", _run, delay=delay)


def _start_resolver() -> None:
    def _run() -> None:
        from internal.council.resolver_scheduler import start_prediction_resolver_scheduler
        from internal.run_mode import is_worker_mode

        default_immediate = "on" if is_worker_mode() else "off"
        immediate = os.environ.get("RESOLVER_BOOT_IMMEDIATE", default_immediate).strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        start_prediction_resolver_scheduler(immediate=immediate)
        logger.info("prediction resolver scheduler started (immediate=%s)", immediate)

        def _recover() -> None:
            try:
                from internal.learning.pump_lead_recover import recover_overdue_pump_leads

                summary = recover_overdue_pump_leads(dry_run=False)
                logger.info("pump_lead recover on boot: %s", summary)
            except Exception as exc:
                logger.warning("pump_lead recover boot failed: %s", exc)

        threading.Thread(target=_recover, daemon=True, name="pump-lead-recover").start()

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


def _start_pick_schedulers() -> None:
    """Phase 1 — traffic-independent daily + hour pick creation (essential)."""

    def _run() -> None:
        from internal.council.pick_scheduler import start_pick_schedulers

        immediate = os.environ.get("PICK_SCHEDULER_BOOT_IMMEDIATE", "off").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        start_pick_schedulers(immediate=immediate)
        logger.info("daily/hour pick schedulers started")

    # After resolver (+10); avoid coinciding with pump first scan.
    defer_boot("pick-schedulers", _run, delay=max(BOOT_DEFER_SECONDS + 20, 60))


def _message_intel_enabled() -> bool:
    flag = os.environ.get("MESSAGE_INTEL_LISTENER", "auto").strip().lower()
    return flag not in ("off", "false", "0", "no")


def _maybe_start_message_intel() -> None:
    """Telegram ingest on essential worker — deferred so HTTP wins boot (ponytail)."""
    if not _message_intel_enabled():
        return

    def _listeners() -> None:
        from internal.message_intel.listener_service import start_message_intel_listeners

        start_message_intel_listeners()

    def _outcomes() -> None:
        from internal.message_intel.outcome_loop import start_price_outcome_loop

        start_price_outcome_loop()

    # After pump first scan window — full heavy mode wedged prod with live subnets + Telegram.
    delay = max(BOOT_DEFER_SECONDS + 60, 120)
    defer_boot("message-intel-listeners", _listeners, delay=delay)
    defer_boot("message-intel-outcomes", _outcomes, delay=max(delay + 30, 150))


def _start_score_snapshot_scheduler() -> None:
    """Phase 2 — full-universe scores off the hot path (essential / worker)."""

    def _run() -> None:
        from internal.council.score_snapshots import start_score_snapshot_scheduler
        from internal.run_mode import is_worker_mode

        default_immediate = "on" if is_worker_mode() else "off"
        immediate = os.environ.get("SCORE_SNAPSHOT_BOOT_IMMEDIATE", default_immediate).strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        start_score_snapshot_scheduler(immediate=immediate)
        logger.info("score snapshot scheduler started (immediate=%s)", immediate)

    # After pick schedulers; full score is heavier.
    defer_boot("score-snapshots", _run, delay=max(BOOT_DEFER_SECONDS + 45, 90))


def _start_pick_audit_scheduler() -> None:
    """Nightly selection oracle replay (evidence loop — Python only)."""

    def _run() -> None:
        from internal.council.pick_audit_scheduler import start_pick_audit_scheduler

        immediate = os.environ.get("PICK_AUDIT_BOOT_IMMEDIATE", "off").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        start_pick_audit_scheduler(immediate=immediate)
        logger.info("pick selection audit scheduler started (immediate=%s)", immediate)

    defer_boot("pick-audit-scheduler", _run, delay=max(BOOT_DEFER_SECONDS + 50, 95))


def _start_pump_desk_snapshot_scheduler() -> None:
    """Periodic pump desk + learning health snapshot (replaces Ditto 15m fetch)."""

    def _run() -> None:
        from internal.pump.desk_snapshot_scheduler import start_pump_desk_snapshot_scheduler

        immediate = os.environ.get("PUMP_DESK_SNAPSHOT_BOOT_IMMEDIATE", "off").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        start_pump_desk_snapshot_scheduler(immediate=immediate)
        logger.info("pump desk snapshot scheduler started (immediate=%s)", immediate)

    defer_boot("pump-desk-snapshot", _run, delay=max(BOOT_DEFER_SECONDS + 55, 100))


def _start_outcome_snapshot_scheduler() -> None:
    """Learning outcome + council health artifact (Ditto Health Monitor feed)."""

    def _run() -> None:
        from internal.learning.outcome_snapshot_scheduler import start_outcome_snapshot_scheduler

        immediate = os.environ.get("OUTCOME_SNAPSHOT_BOOT_IMMEDIATE", "off").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        start_outcome_snapshot_scheduler(immediate=immediate)
        logger.info("outcome snapshot scheduler started (immediate=%s)", immediate)

    defer_boot("outcome-snapshot", _run, delay=max(BOOT_DEFER_SECONDS + 60, 105))


def start_background_workers(*, heavy: Optional[bool] = None) -> None:
    """Start background schedulers.

    * **essential** (default on web with ``BACKGROUND_ON_WEB=essential``): pump
      ladder, resolver, whale warm, registry freshness, and (when enabled)
      deferred Telegram message-intel — no live-subnet wedge.
    * **heavy** (worker or ``BACKGROUND_ON_WEB=on``): also live subnets and feed
      warmup on top of essential.
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
    _start_pick_schedulers()
    _start_score_snapshot_scheduler()
    _start_pick_audit_scheduler()
    _start_pump_desk_snapshot_scheduler()
    _start_outcome_snapshot_scheduler()

    _maybe_start_message_intel()

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


def stop_background_workers() -> None:
    try:
        from internal.message_intel.listener_service import stop_message_intel_listeners

        stop_message_intel_listeners()
    except Exception:
        pass
    try:
        from internal.message_intel.outcome_loop import stop_price_outcome_loop

        stop_price_outcome_loop()
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
        from internal.council.pick_scheduler import stop_pick_schedulers

        stop_pick_schedulers()
    except Exception:
        pass
    try:
        from internal.council.pick_audit_scheduler import stop_pick_audit_scheduler

        stop_pick_audit_scheduler()
    except Exception:
        pass
    try:
        from internal.pump.desk_snapshot_scheduler import stop_pump_desk_snapshot_scheduler

        stop_pump_desk_snapshot_scheduler()
    except Exception:
        pass
    try:
        from internal.learning.outcome_snapshot_scheduler import stop_outcome_snapshot_scheduler

        stop_outcome_snapshot_scheduler()
    except Exception:
        pass
    try:
        from internal.council.score_snapshots import stop_score_snapshot_scheduler

        stop_score_snapshot_scheduler()
    except Exception:
        pass
    try:
        from internal.job_scheduler import cancel_job, shutdown_background_scheduler

        cancel_job("whale-ledger-warm")
        shutdown_background_scheduler()
    except Exception:
        pass
