"""Periodic pump desk snapshot on inline worker (replaces Ditto 15m fetch)."""

from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, Optional

from internal.job_scheduler import cancel_job, schedule_interval_seconds

logger = logging.getLogger(__name__)

JOB_ID = "pump-desk-snapshot"
INTERVAL_MINUTES = int(os.environ.get("PUMP_DESK_SNAPSHOT_MINUTES", "15"))

_lock = threading.Lock()
_scheduler: Optional["PumpDeskSnapshotScheduler"] = None


def _enabled() -> bool:
    return os.environ.get("PUMP_DESK_SNAPSHOT_ENABLED", "on").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


class PumpDeskSnapshotScheduler:
    def __init__(self, interval_minutes: int = INTERVAL_MINUTES) -> None:
        self.interval_minutes = max(5, min(int(interval_minutes), 60))
        self._running = False
        self._last_result: Dict[str, Any] = {}

    def start(self, immediate: bool = False) -> Dict[str, Any]:
        with _lock:
            if self._running:
                return {"started": False, "reason": "already running"}
            self._running = True
        delay = 30 if immediate else max(60, self.interval_minutes * 60)
        schedule_interval_seconds(
            JOB_ID,
            self._tick,
            self.interval_minutes * 60,
            start_delay_seconds=delay,
        )
        return {"started": True, "interval_minutes": self.interval_minutes}

    def stop(self) -> Dict[str, Any]:
        with _lock:
            self._running = False
        cancel_job(JOB_ID)
        return {"stopped": True}

    def state(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "interval_minutes": self.interval_minutes,
            "last_result": self._last_result,
        }

    def run_once(self) -> Dict[str, Any]:
        return self._tick()

    def _tick(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"ok": False}
        try:
            from internal.pump.desk_snapshot import run_snapshot

            payload = run_snapshot(save=True)
            result["ok"] = True
            result["alert_level"] = payload.get("alert_level")
            result["path"] = payload.get("path")
            result["actionable_count"] = len(payload.get("actionable_badges") or [])
            if payload.get("alert_level") == "alert":
                logger.warning(
                    "pump desk snapshot ALERT: %s",
                    payload.get("alert_reasons"),
                )
        except Exception as exc:
            result["error"] = str(exc)
            logger.warning("pump desk snapshot tick failed: %s", exc)

        with _lock:
            self._last_result = dict(result)
        return result


def start_pump_desk_snapshot_scheduler(immediate: bool = False) -> Dict[str, Any]:
    if not _enabled():
        return {"started": False, "reason": "disabled"}
    global _scheduler
    with _lock:
        if _scheduler is None:
            _scheduler = PumpDeskSnapshotScheduler()
        sched = _scheduler
    return sched.start(immediate=immediate)


def stop_pump_desk_snapshot_scheduler() -> Dict[str, Any]:
    global _scheduler
    with _lock:
        sched = _scheduler
        _scheduler = None
    if sched is None:
        return {"stopped": False, "reason": "not running"}
    return sched.stop()


def get_pump_desk_snapshot_scheduler_state() -> Dict[str, Any]:
    with _lock:
        return {
            "enabled": _enabled(),
            "scheduler": _scheduler.state() if _scheduler else {"running": False},
        }
