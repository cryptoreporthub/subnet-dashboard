"""
Indicator scheduler — background scheduler for technical indicator computation.
"""

import os
import threading
from typing import Any, Dict, Optional


REFRESH_MINUTES = int(os.environ.get("INDICATOR_REFRESH_MINUTES", "15"))

_scheduler: Optional[threading.Timer] = None
_lock = threading.Lock()
_running = False


def start_indicator_scheduler(immediate: bool = False) -> Dict[str, Any]:
    """Start the indicator background scheduler."""
    global _running
    with _lock:
        if _running:
            return {"started": False, "reason": "already running"}
        _running = True
    return {"started": True, "refresh_minutes": REFRESH_MINUTES}


def stop_indicator_scheduler() -> Dict[str, Any]:
    """Stop the indicator background scheduler."""
    global _running
    with _lock:
        _running = False
    return {"stopped": True}


def get_indicator_scheduler_state() -> Dict[str, Any]:
    """Return the indicator scheduler state."""
    return {
        "running": _running,
        "refresh_minutes": REFRESH_MINUTES,
    }