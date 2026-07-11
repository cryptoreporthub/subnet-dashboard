"""Boot + periodic pump ladder scanner (mirrors selector scheduler pattern)."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from internal.pump.state import scan_all_subnets

logger = logging.getLogger(__name__)

PUMP_LADDER_REFRESH_MINUTES = int(os.environ.get("PUMP_LADDER_REFRESH_MINUTES", "20"))

_scheduler: Optional["PumpLadderScheduler"] = None
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PumpLadderScheduler:
    def __init__(self, refresh_minutes: int = PUMP_LADDER_REFRESH_MINUTES):
        self.refresh_minutes = refresh_minutes
        self._timer: Optional[threading.Timer] = None
        self._running = False
        self._last_run_at: Optional[str] = None
        self._last_ok: Optional[bool] = None
        self._last_error: Optional[str] = None
        self._last_result: Dict[str, Any] = {}

    def start(self, immediate: bool = False) -> Dict[str, Any]:
        with _lock:
            if self._running:
                return {"started": False, "reason": "already running"}
            self._running = True
        if immediate:
            threading.Thread(target=self._tick, daemon=True).start()
        else:
            self._schedule(5)
        return {"started": True, "refresh_minutes": self.refresh_minutes}

    def stop(self) -> Dict[str, Any]:
        with _lock:
            self._running = False
            timer = self._timer
            self._timer = None
        if timer:
            timer.cancel()
        return {"stopped": True}

    def state(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "refresh_minutes": self.refresh_minutes,
            "last_run_at": self._last_run_at,
            "last_run_ok": self._last_ok,
            "last_run_error": self._last_error,
            "last_result": self._last_result,
        }

    def run_once(self) -> Dict[str, Any]:
        return self._tick()

    def _schedule(self, minutes: int) -> None:
        with _lock:
            if not self._running:
                return
            self._timer = threading.Timer(minutes * 60, self._tick)
            self._timer.daemon = True
            self._timer.start()

    def _tick(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"ok": False, "run_at": _now_iso(), "error": None}
        try:
            scan = scan_all_subnets()
            result.update(scan)
            result["ok"] = bool(scan.get("ok"))
        except Exception as exc:
            result["error"] = str(exc)
            logger.warning("Pump ladder scan failed: %s", exc)

        with _lock:
            self._last_run_at = result["run_at"]
            self._last_ok = result.get("ok")
            self._last_error = result.get("error")
            self._last_result = {
                k: result.get(k)
                for k in ("scanned", "transitions", "phase_counts", "soul_map")
                if k in result
            }

        if self._running:
            self._schedule(self.refresh_minutes)
        return result


def start_pump_ladder_scheduler(immediate: bool = False) -> Dict[str, Any]:
    global _scheduler
    with _lock:
        if _scheduler is None:
            _scheduler = PumpLadderScheduler()
    return _scheduler.start(immediate=immediate)


def stop_pump_ladder_scheduler() -> Dict[str, Any]:
    global _scheduler
    sched: Optional[PumpLadderScheduler] = None
    with _lock:
        sched = _scheduler
        _scheduler = None
    if sched is None:
        return {"stopped": False, "reason": "not running"}
    return sched.stop()


def get_pump_ladder_scheduler_state() -> Dict[str, Any]:
    with _lock:
        if _scheduler is None:
            return {"running": False, "refresh_minutes": PUMP_LADDER_REFRESH_MINUTES}
        return _scheduler.state()


def ensure_pump_ladder_scheduler(immediate: bool = False) -> Dict[str, Any]:
    """Idempotent start used by analytics/resolver boot hooks."""
    with _lock:
        if _scheduler is not None and _scheduler._running:
            return {"started": False, "reason": "already running"}
    return start_pump_ladder_scheduler(immediate=immediate)
