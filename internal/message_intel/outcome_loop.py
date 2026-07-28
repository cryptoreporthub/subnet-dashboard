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
_heartbeat_stop: Optional[Any] = None
_DEFAULT_HEARTBEAT = "data/.message_intel_outcome_loop"


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
    return _tracker is not None and bool(getattr(_tracker, "_running", False))


def _start_heartbeat_loop() -> None:
    global _heartbeat_stop
    if _heartbeat_stop is not None:
        return
    stop = threading.Event()
    _heartbeat_stop = stop

    def _loop() -> None:
        while not stop.wait(60):
            if not _outcome_running_local():
                break
            try:
                _touch_outcome_heartbeat()
            except Exception as exc:
                logger.debug("outcome heartbeat refresh failed: %s", exc)

    threading.Thread(target=_loop, daemon=True, name="mi-outcome-heartbeat").start()


def _stop_heartbeat_loop() -> None:
    global _heartbeat_stop
    if _heartbeat_stop is not None:
        _heartbeat_stop.set()
        _heartbeat_stop = None


def start_price_outcome_loop(*, interval: int = 300) -> bool:
    """Start periodic outcome checks against message price snapshots."""
    global _tracker
    if _outcome_running_local():
        return True
    try:
        from internal.message_intel.store import get_db
        from message_intel.price_tracker import PriceTracker

        tracker = PriceTracker(db=get_db())
        tracker.start_background_checks(interval=interval)
        _tracker = tracker
        _touch_outcome_heartbeat()
        _start_heartbeat_loop()
        logger.info("Message-intel price outcome loop started (interval=%ds)", interval)
        return True
    except Exception as exc:
        logger.warning("Price outcome loop failed to start: %s", exc)
        _tracker = None
        return False


def stop_price_outcome_loop() -> None:
    global _tracker
    _stop_heartbeat_loop()
    if _tracker is None:
        _clear_outcome_heartbeat()
        return
    try:
        _tracker._running = False
    except Exception:
        pass
    _tracker = None
    _clear_outcome_heartbeat()


def outcome_loop_status() -> dict:
    running = _outcome_running_local() or _outcome_alive_cross_process()
    return {"running": running, "live": running}
