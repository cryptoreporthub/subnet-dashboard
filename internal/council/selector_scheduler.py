"""Background scheduler for daily Selector rotation (Soul-Map sync)."""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SELECTOR_REFRESH_MINUTES = int(os.environ.get("SELECTOR_REFRESH_MINUTES", "360"))
SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")

_scheduler: Optional["SelectorScheduler"] = None
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SelectorScheduler:
    def __init__(self, refresh_minutes: int = SELECTOR_REFRESH_MINUTES):
        self.refresh_minutes = refresh_minutes
        self._timer: Optional[threading.Timer] = None
        self._running = False
        self._last_run_at: Optional[str] = None
        self._last_ok: Optional[bool] = None
        self._last_error: Optional[str] = None

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
        result = {"ok": False, "run_at": _now_iso(), "error": None}
        try:
            from internal.council.orchestrator import Orchestrator
            from internal.learning.alignment_nudge import apply_alignment_nudge
            from internal.learning.trail_bus import emit_disposition_shift

            orch = Orchestrator()
            subnet_ids = None
            try:
                from fetchers.taomarketcap import get_all_subnets

                ranked = sorted(
                    get_all_subnets() or [],
                    key=lambda s: float(s.get("emission", 0) or 0),
                    reverse=True,
                )
                subnet_ids = [s.get("netuid") for s in ranked[:24] if s.get("netuid") is not None]
            except Exception:
                subnet_ids = None
            rotation = orch.run_daily_rotation(subnet_ids=subnet_ids)
            feedback = (rotation or {}).get("feedback_loop") or {}
            if feedback:
                result["alignment"] = apply_alignment_nudge(feedback)
            emit_disposition_shift(
                evidence={"rotation_decisions": len((rotation.get("daily_output") or {}).get("decisions", []))},
                to_action="daily_rotation_complete",
            )
            result["ok"] = True
            result["decisions"] = len((rotation.get("daily_output") or {}).get("decisions", []))
        except Exception as exc:
            result["error"] = str(exc)
            logger.warning("Selector rotation tick failed: %s", exc)

        with _lock:
            self._last_run_at = result["run_at"]
            self._last_ok = result["ok"]
            self._last_error = result.get("error")

        if self._running:
            self._schedule(self.refresh_minutes)
        return result


def start_selector_scheduler(immediate: bool = False) -> Dict[str, Any]:
    global _scheduler
    with _lock:
        if _scheduler is None:
            _scheduler = SelectorScheduler()
    return _scheduler.start(immediate=immediate)


def stop_selector_scheduler() -> Dict[str, Any]:
    global _scheduler
    sched: Optional[SelectorScheduler] = None
    with _lock:
        sched = _scheduler
        _scheduler = None
    if sched is None:
        return {"stopped": False, "reason": "not running"}
    return sched.stop()


def get_selector_scheduler_state() -> Dict[str, Any]:
    with _lock:
        if _scheduler is None:
            return {"running": False, "refresh_minutes": SELECTOR_REFRESH_MINUTES}
        return _scheduler.state()
