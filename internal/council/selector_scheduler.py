"""Background scheduler for daily Selector rotation (Soul-Map sync)."""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from internal.job_scheduler import cancel_job, schedule_in_seconds
from internal.liveness import LivenessTracker

logger = logging.getLogger(__name__)

SELECTOR_REFRESH_MINUTES = int(os.environ.get("SELECTOR_REFRESH_MINUTES", "360"))
SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")
JOB_ID = "selector-scheduler"

_scheduler: Optional["SelectorScheduler"] = None
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SelectorScheduler:
    def __init__(self, refresh_minutes: int = SELECTOR_REFRESH_MINUTES):
        self.refresh_minutes = refresh_minutes
        self._active = False
        self._last_tick_at: Optional[str] = None
        self._last_error: Optional[str] = None
        self.liveness = LivenessTracker(
            name="selector_rotation",
            interval_seconds=max(60, int(refresh_minutes) * 60),
            staleness_factor=2,
            persist=True,
        )

    def start(self, immediate: bool = False) -> Dict[str, Any]:
        with _lock:
            if self._active:
                return {"started": False, "reason": "already running"}
            self._active = True
        self.liveness.start()
        if immediate:
            threading.Thread(target=self._tick, daemon=True).start()
        else:
            self._schedule(5)
        return {"started": True, "refresh_minutes": self.refresh_minutes}

    def stop(self) -> Dict[str, Any]:
        with _lock:
            self._active = False
        cancel_job(JOB_ID)
        return {"stopped": True}

    def state(self) -> Dict[str, Any]:
        snap = self.liveness.snapshot()
        return {
            "running": self._active,
            "refresh_minutes": self.refresh_minutes,
            "last_run_at": self._last_tick_at,
            "last_run_ok": snap["status"] == "ok",
            "last_run_error": self._last_error,
            "liveness": snap,
        }

    def run_once(self) -> Dict[str, Any]:
        return self._tick()

    def _schedule(self, minutes: int) -> None:
        with _lock:
            if not self._active:
                return
        schedule_in_seconds(JOB_ID, self._tick, minutes * 60)

    def _tick(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"ok": False, "run_at": _now_iso(), "error": None}
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
            decisions = len((rotation.get("daily_output") or {}).get("decisions", []))
            result["ok"] = True
            result["decisions"] = decisions
            self.liveness.record_success(
                evidence={"decisions": decisions, "op": "daily_rotation"},
            )
        except Exception as exc:
            result["error"] = str(exc)
            self.liveness.record_failure(error=str(exc))
            logger.warning("Selector rotation tick failed: %s", exc)

        with _lock:
            self._last_tick_at = result["run_at"]
            self._last_error = result.get("error")

        if self._active:
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


def _stopped_liveness_ok() -> Optional[bool]:
    try:
        from internal.liveness import get_tracker

        t = get_tracker("selector_rotation")
        if t is not None:
            return t.snapshot()["status"] == "ok"
    except Exception:
        pass
    return None


def get_selector_scheduler_state() -> Dict[str, Any]:
    with _lock:
        if _scheduler is None:
            return {
                "running": False,
                "refresh_minutes": SELECTOR_REFRESH_MINUTES,
                "last_run_at": None,
                "last_run_ok": _stopped_liveness_ok(),
                "last_run_error": None,
            }
        return _scheduler.state()
