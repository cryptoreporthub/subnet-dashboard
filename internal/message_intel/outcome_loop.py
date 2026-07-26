"""Price outcome background loop for message-intel (Telegram → snapshot → grade)."""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_tracker: Any = None


def start_price_outcome_loop(*, interval: int = 300) -> bool:
    """Start periodic outcome checks against message price snapshots."""
    global _tracker
    if _tracker is not None and getattr(_tracker, "_running", False):
        return True
    try:
        from internal.message_intel.store import get_db
        from message_intel.price_tracker import PriceTracker

        tracker = PriceTracker(db=get_db())
        tracker.start_background_checks(interval=interval)
        _tracker = tracker
        logger.info("Message-intel price outcome loop started (interval=%ds)", interval)
        return True
    except Exception as exc:
        logger.warning("Price outcome loop failed to start: %s", exc)
        _tracker = None
        return False


def stop_price_outcome_loop() -> None:
    global _tracker
    if _tracker is None:
        return
    try:
        _tracker._running = False
    except Exception:
        pass
    _tracker = None


def outcome_loop_status() -> dict:
    running = bool(_tracker is not None and getattr(_tracker, "_running", False))
    return {"running": running, "live": running}
