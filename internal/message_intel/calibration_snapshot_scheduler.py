"""Daily Telegram calibration health snapshot scheduler.

Mirrors the pattern of ``internal/learning/outcome_snapshot_scheduler.py``.
Runs once per day at the configured UTC slot (not boot-relative) and warns
when the calibration factor has drifted beyond the configured epsilon compared
with the previous snapshot.

Scheduling discipline
---------------------
* First tick is scheduled at ``_seconds_until_slot()`` — the real wall-clock
  distance to the configured UTC slot — so it fires close to 05:15 UTC
  regardless of when the process booted.
* After each tick completes, the next run is again scheduled via
  ``_seconds_until_slot()`` so the job always re-anchors to the configured
  slot rather than drifting by the exact runtime of the previous tick.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from internal.job_scheduler import cancel_job, schedule_in_seconds
from internal.liveness import LivenessTracker

logger = logging.getLogger(__name__)

JOB_ID = "calibration-snapshot"
SLOT_HOUR = int(os.environ.get("CALIBRATION_SNAPSHOT_UTC_HOUR", "5"))
SLOT_MINUTE = int(os.environ.get("CALIBRATION_SNAPSHOT_UTC_MINUTE", "15"))

_lock = threading.Lock()
_scheduler: Optional["CalibrationSnapshotScheduler"] = None


def _enabled() -> bool:
    return os.environ.get("CALIBRATION_SNAPSHOT_ENABLED", "on").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _seconds_until_slot(now: Optional[datetime] = None) -> float:
    """Return seconds until the next occurrence of the configured UTC slot."""
    now = now or datetime.now(timezone.utc)
    target = now.replace(
        hour=max(0, min(23, SLOT_HOUR)),
        minute=max(0, min(59, SLOT_MINUTE)),
        second=0,
        microsecond=0,
    )
    if target <= now:
        target = target + timedelta(days=1)
    return max(30.0, (target - now).total_seconds())


def _next_slot_dt(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now + timedelta(seconds=_seconds_until_slot(now))


def _stopped_scheduler_state() -> Dict[str, Any]:
    snap: Dict[str, Any] = {}
    try:
        from internal.liveness import get_tracker

        t = get_tracker("calibration_snapshot")
        if t is not None:
            snap = t.snapshot()
    except Exception:
        pass
    return {
        "running": False,
        "last_result": {},
        "slot_utc": f"{SLOT_HOUR:02d}:{SLOT_MINUTE:02d}",
        "next_run_at": None,
        "liveness": snap,
    }


class CalibrationSnapshotScheduler:
    def __init__(self) -> None:
        self._last_result: Dict[str, Any] = {}
        self._next_run_at: Optional[str] = None
        self.liveness = LivenessTracker(
            name="calibration_snapshot",
            interval_seconds=max(3600, int(_seconds_until_slot())),
            staleness_factor=2,
            persist=True,
        )

    def _is_registered(self) -> bool:
        with _lock:
            return _scheduler is self

    def start(self, immediate: bool = False) -> Dict[str, Any]:
        if not self._is_registered():
            return {"started": False, "reason": "not registered"}
        snap = self.liveness.snapshot()
        if snap.get("lifecycle") == "started":
            return {"started": False, "reason": "already running"}
        self.liveness.start()
        if immediate:
            threading.Thread(
                target=self._tick, daemon=True, name="calibration-snapshot-tick"
            ).start()
        else:
            delay = _seconds_until_slot()
            next_dt = _next_slot_dt()
            with _lock:
                self._next_run_at = next_dt.isoformat().replace("+00:00", "Z")
            schedule_in_seconds(JOB_ID, self._tick, delay)
        return {
            "started": True,
            "slot_utc": f"{SLOT_HOUR:02d}:{SLOT_MINUTE:02d}",
            "next_run_at": self._next_run_at,
        }

    def stop(self) -> Dict[str, Any]:
        with _lock:
            self._next_run_at = None
        cancel_job(JOB_ID)
        return {"stopped": True}

    def state(self) -> Dict[str, Any]:
        snap = self.liveness.snapshot()
        with _lock:
            return {
                "running": snap.get("lifecycle") == "started",
                "last_result": dict(self._last_result),
                "slot_utc": f"{SLOT_HOUR:02d}:{SLOT_MINUTE:02d}",
                "next_run_at": self._next_run_at,
                "liveness": snap,
            }

    def run_once(self) -> Dict[str, Any]:
        return self._tick(reschedule=False)

    def _tick(self, reschedule: bool = True) -> Dict[str, Any]:
        result: Dict[str, Any] = {"ok": False}
        try:
            from internal.message_intel.calibration_snapshot import run_calibration_snapshot

            payload = run_calibration_snapshot(save=True)
            result["ok"] = True
            result["alert_level"] = payload.get("alert_level")
            result["drifted"] = (payload.get("drift") or {}).get("drifted")
            result["factor"] = (payload.get("calibration_health") or {}).get("factor")
            result["path"] = payload.get("path")
            self.liveness.record_success(
                evidence={
                    "factor": result.get("factor"),
                    "drifted": bool(result.get("drifted")),
                    "op": "calibration_snapshot",
                }
            )
            if payload.get("alert_level") in ("warn", "alert"):
                logger.warning(
                    "calibration snapshot %s: %s",
                    payload.get("alert_level"),
                    payload.get("alert_reasons"),
                )
        except Exception as exc:
            result["error"] = str(exc)
            self.liveness.record_failure(error=str(exc))
            logger.warning("calibration snapshot tick failed: %s", exc)

        if reschedule and self._is_registered():
            delay = _seconds_until_slot()
            next_dt = _next_slot_dt()
            next_iso = next_dt.isoformat().replace("+00:00", "Z")
            with _lock:
                self._next_run_at = next_iso
                self._last_result = dict(result)
            result["next_run_at"] = next_iso
            schedule_in_seconds(JOB_ID, self._tick, delay)
        else:
            with _lock:
                self._last_result = dict(result)

        return result


def start_calibration_snapshot_scheduler(immediate: bool = False) -> Dict[str, Any]:
    if not _enabled():
        return {"started": False, "reason": "disabled"}
    global _scheduler
    with _lock:
        if _scheduler is not None:
            snap = _scheduler.liveness.snapshot()
            if snap.get("lifecycle") == "started":
                return {"started": False, "reason": "already running"}
        else:
            _scheduler = CalibrationSnapshotScheduler()
    return _scheduler.start(immediate=immediate)


def stop_calibration_snapshot_scheduler() -> Dict[str, Any]:
    global _scheduler
    with _lock:
        sched = _scheduler
        _scheduler = None
    if sched is None:
        return {"stopped": False, "reason": "not running"}
    return sched.stop()


def get_calibration_snapshot_scheduler_state() -> Dict[str, Any]:
    with _lock:
        return {
            "enabled": _enabled(),
            "scheduler": _scheduler.state() if _scheduler else _stopped_scheduler_state(),
        }
