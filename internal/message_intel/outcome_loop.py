"""Price outcome background loop for message-intel (Telegram → snapshot → grade)."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_tracker: Any = None
_watchdog_stop: Optional[Any] = None
_recovery_pending = False
_DEFAULT_HEARTBEAT = "data/.message_intel_outcome_loop"
_WATCHDOG_CHECK_SECONDS = 60
_WATCHDOG_STALE_SECONDS = int(os.environ.get("OUTCOME_LOOP_WATCHDOG_STALE_SECONDS", "420"))
_TRACKER_JOIN_TIMEOUT_SECONDS = float(
    os.environ.get("OUTCOME_LOOP_TRACKER_JOIN_TIMEOUT_SECONDS", "15")
)


def _heartbeat_path() -> str:
    return os.environ.get("MESSAGE_INTEL_OUTCOME_HEARTBEAT", _DEFAULT_HEARTBEAT)


def _touch_outcome_heartbeat() -> None:
    path = _heartbeat_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def _clear_outcome_heartbeat() -> None:
    try:
        os.remove(_heartbeat_path())
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.debug("outcome heartbeat clear failed: %s", exc)


def _outcome_alive_cross_process(*, max_age_seconds: int = 360) -> bool:
    """ponytail: default 6m — outcome loop interval is 5m."""
    try:
        with open(_heartbeat_path(), "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict) or not raw.get("ts"):
            return False
        ts = datetime.fromisoformat(str(raw["ts"]).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
        return age <= max_age_seconds
    except Exception:
        return False


def _outcome_running_local() -> bool:
    if _tracker is None:
        return False
    if bool(getattr(_tracker, "_running", False)):
        return True
    thread = getattr(_tracker, "_thread", None)
    return thread is not None and thread.is_alive()


def _recovery_thread_alive() -> bool:
    thread = getattr(_tracker, "_thread", None) if _tracker is not None else None
    return thread is not None and thread.is_alive()


# ── Watchdog (audit infra item 3) ────────────────────────────────────────
# Copy the listener's mature heartbeat/watchdog-restart pattern: if the
# outcome loop reports running but its heartbeat goes stale (wedged thread),
# stop and restart it so a hung resolve pass heals itself.


def _start_outcome_watchdog(*, interval: int = 300) -> None:
    global _watchdog_stop
    if _watchdog_stop is not None:
        return
    stop = threading.Event()
    _watchdog_stop = stop

    def _watch() -> None:
        while not stop.wait(_WATCHDOG_CHECK_SECONDS):
            try:
                if _recovery_pending:
                    if _recovery_thread_alive():
                        continue
                    _restart_outcome_loop(interval=interval)
                    continue
                if not _outcome_running_local():
                    continue
                # Stale heartbeat while locally "running" == wedged tick loop.
                if _outcome_alive_cross_process(max_age_seconds=_WATCHDOG_STALE_SECONDS):
                    continue
                logger.warning(
                    "outcome watchdog: heartbeat stale >%ds — restarting loop",
                    _WATCHDOG_STALE_SECONDS,
                )
                _restart_outcome_loop(interval=interval)
            except Exception as exc:
                logger.debug("outcome watchdog tick failed: %s", exc)

    threading.Thread(target=_watch, daemon=True, name="mi-outcome-watchdog").start()


def _stop_outcome_watchdog() -> None:
    global _watchdog_stop
    if _watchdog_stop is not None:
        _watchdog_stop.set()
        _watchdog_stop = None


def _restart_outcome_loop(*, interval: int = 300) -> None:
    """Stop and start the outcome loop without overlapping checker threads."""
    global _recovery_pending, _tracker
    old = _tracker
    if old is not None:
        try:
            stop = getattr(old, "stop_background_checks", None)
            if callable(stop):
                stopped = bool(
                    stop(join_timeout=_TRACKER_JOIN_TIMEOUT_SECONDS)
                )
            else:
                old._running = False
                thread = getattr(old, "_thread", None)
                if thread is not None and thread is not threading.current_thread():
                    thread.join(timeout=_TRACKER_JOIN_TIMEOUT_SECONDS)
                stopped = thread is None or not thread.is_alive()
        except Exception:
            stopped = False
        if not stopped:
            _recovery_pending = True
            logger.warning(
                "outcome watchdog: old checker still alive; refusing overlapping restart"
            )
            _clear_outcome_heartbeat()
            return
    _clear_outcome_heartbeat()
    try:
        from internal.message_intel.store import get_db
        from message_intel.price_tracker import PriceTracker

        tracker = PriceTracker(
            db=get_db(), progress_callback=_touch_outcome_heartbeat
        )
        tracker.start_background_checks(interval=interval)
        _tracker = tracker
        _recovery_pending = False
        _touch_outcome_heartbeat()
        logger.info("outcome watchdog: loop restarted (interval=%ds)", interval)
    except Exception as exc:
        logger.warning("outcome watchdog restart failed: %s", exc)
        _tracker = old


def start_price_outcome_loop(*, interval: int = 300) -> bool:
    """Start periodic outcome checks against message price snapshots."""
    global _recovery_pending, _tracker
    if _outcome_running_local():
        return True
    try:
        from internal.message_intel.store import get_db
        from message_intel.price_tracker import PriceTracker

        tracker = PriceTracker(
            db=get_db(), progress_callback=_touch_outcome_heartbeat
        )
        tracker.start_background_checks(interval=interval)
        _tracker = tracker
        _recovery_pending = False
        _touch_outcome_heartbeat()
        _start_outcome_watchdog(interval=interval)
        logger.info("Message-intel price outcome loop started (interval=%ds)", interval)
        return True
    except Exception as exc:
        logger.warning("Price outcome loop failed to start: %s", exc)
        _tracker = None
        return False


def stop_price_outcome_loop() -> None:
    global _recovery_pending, _tracker
    _stop_outcome_watchdog()
    _recovery_pending = False
    if _tracker is None:
        _clear_outcome_heartbeat()
        return
    try:
        stop = getattr(_tracker, "stop_background_checks", None)
        if callable(stop):
            stop(join_timeout=_TRACKER_JOIN_TIMEOUT_SECONDS)
        else:
            _tracker._running = False
            thread = getattr(_tracker, "_thread", None)
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=_TRACKER_JOIN_TIMEOUT_SECONDS)
    except Exception:
        logger.debug("outcome checker stop failed", exc_info=True)
    _tracker = None
    _clear_outcome_heartbeat()


def outcome_loop_status() -> dict:
    running = _outcome_running_local() or _outcome_alive_cross_process()
    return {"running": running, "live": running}
