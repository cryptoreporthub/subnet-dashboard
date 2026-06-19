"""
Background scheduler for the technical indicator layer.

Lightweight thread-based timer similar to the adversarial scheduler.
"""

import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from indicators.indicator_engine import IndicatorEngine
from indicators.learning import tune_thresholds_from_verdicts

INDICATOR_REFRESH_MINUTES = int(os.environ.get("INDICATOR_REFRESH_MINUTES", "15"))
TUNE_INDICATOR_WEIGHTS = (
    os.environ.get("TUNE_INDICATOR_WEIGHTS", "true").lower() != "false"
)


class IndicatorScheduler:
    """Periodically refresh technical indicators."""

    def __init__(
        self,
        refresh_minutes: int = INDICATOR_REFRESH_MINUTES,
        engine: Optional[IndicatorEngine] = None,
    ):
        self.refresh_minutes = refresh_minutes
        self.engine = engine or IndicatorEngine()
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._running = False
        self._last_run_at: Optional[str] = None
        self._last_run_ok: Optional[bool] = None
        self._last_run_error: Optional[str] = None
        self._next_run_at: Optional[str] = None

    def start(self, immediate: bool = False) -> Dict[str, Any]:
        with self._lock:
            if self._running:
                return {"started": False, "reason": "already running"}
            self._running = True

        if immediate:
            self._tick()
        else:
            self._schedule_next(self.refresh_minutes)

        return {
            "started": True,
            "refresh_minutes": self.refresh_minutes,
            "next_run_at": self._next_run_at,
        }

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            self._running = False
            self._next_run_at = None
            timer = self._timer
            self._timer = None
        if timer:
            timer.cancel()
        return {"stopped": True}

    def state(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "refresh_minutes": self.refresh_minutes,
                "last_run_at": self._last_run_at,
                "last_run_ok": self._last_run_ok,
                "last_run_error": self._last_run_error,
                "next_run_at": self._next_run_at,
            }

    def run_once(self) -> Dict[str, Any]:
        return self._execute()

    def _schedule_next(self, minutes: int) -> None:
        with self._lock:
            if not self._running:
                return
            self._next_run_at = (
                datetime.now(timezone.utc).timestamp() + minutes * 60
            )
            self._timer = threading.Timer(minutes * 60, self._tick)
            self._timer.daemon = True
            self._timer.start()

    def _tick(self) -> None:
        result = self._execute()
        if self._running:
            self._schedule_next(self.refresh_minutes)
        return result

    def _execute(self) -> Dict[str, Any]:
        run_at = datetime.now(timezone.utc).isoformat()
        result = {
            "ok": False,
            "run_at": run_at,
            "pairs": 0,
            "error": None,
        }
        try:
            state = self.engine.run()
            result["ok"] = True
            result["pairs"] = len(state.get("signals", []))
            result["updated_at"] = state.get("updated_at")
            if TUNE_INDICATOR_WEIGHTS:
                tune_thresholds_from_verdicts()
        except Exception as exc:
            result["error"] = str(exc)

        with self._lock:
            self._last_run_at = run_at
            self._last_run_ok = result["ok"]
            self._last_run_error = result.get("error")
        return result


# Module-level singleton for server.py
_scheduler: Optional[IndicatorScheduler] = None
_scheduler_lock = threading.Lock()


def start_indicator_scheduler(
    refresh_minutes: int = INDICATOR_REFRESH_MINUTES,
    immediate: bool = False,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Start the module-level indicator scheduler singleton."""
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = IndicatorScheduler(refresh_minutes=refresh_minutes, **kwargs)
        return _scheduler.start(immediate=immediate)


def stop_indicator_scheduler() -> Dict[str, Any]:
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            return {"stopped": False, "reason": "not running"}
        result = _scheduler.stop()
        _scheduler = None
        return result


def get_indicator_scheduler_state() -> Dict[str, Any]:
    with _scheduler_lock:
        if _scheduler is None:
            return {
                "running": False,
                "refresh_minutes": INDICATOR_REFRESH_MINUTES,
                "last_run_at": None,
                "last_run_ok": None,
                "last_run_error": None,
                "next_run_at": None,
            }
        return _scheduler.state()
