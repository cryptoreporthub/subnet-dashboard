"""Daily learning outcome snapshot on inline worker (Council Health Monitor feed)."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from internal.job_scheduler import cancel_job, schedule_in_seconds

logger = logging.getLogger(__name__)

JOB_ID = "learning-outcome-snapshot"
SLOT_HOUR = int(os.environ.get("OUTCOME_SNAPSHOT_UTC_HOUR", "4"))
SLOT_MINUTE = int(os.environ.get("OUTCOME_SNAPSHOT_UTC_MINUTE", "50"))
INTERVAL_HOURS = int(os.environ.get("OUTCOME_SNAPSHOT_INTERVAL_HOURS", "6"))

_lock = threading.Lock()
_scheduler: Optional["OutcomeSnapshotScheduler"] = None


def _enabled() -> bool:
    return os.environ.get("OUTCOME_SNAPSHOT_ENABLED", "on").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _seconds_until_slot() -> float:
    now = datetime.now(timezone.utc)
    target = now.replace(
        hour=max(0, min(23, SLOT_HOUR)),
        minute=max(0, min(59, SLOT_MINUTE)),
        second=0,
        microsecond=0,
    )
    if target <= now:
        target = target + timedelta(days=1)
    return max(30.0, (target - now).total_seconds())


def _interval_seconds() -> int:
    return max(3600, min(INTERVAL_HOURS * 3600, 86400))


class OutcomeSnapshotScheduler:
    def __init__(self) -> None:
        self._running = False
        self._last_result: Dict[str, Any] = {}

    def start(self, immediate: bool = False) -> Dict[str, Any]:
        with _lock:
            if self._running:
                return {"started": False, "reason": "already running"}
            self._running = True
        if immediate:
            threading.Thread(target=self._tick, daemon=True, name="outcome-snapshot-tick").start()
        else:
            # First tick soon after worker boot; then interval cadence.
            schedule_in_seconds(JOB_ID, self._tick, min(120.0, _seconds_until_slot()))
        return {
            "started": True,
            "slot_utc": f"{SLOT_HOUR:02d}:{SLOT_MINUTE:02d}",
            "interval_hours": INTERVAL_HOURS,
        }

    def stop(self) -> Dict[str, Any]:
        with _lock:
            self._running = False
        cancel_job(JOB_ID)
        return {"stopped": True}

    def state(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "last_result": self._last_result,
            "slot_utc": f"{SLOT_HOUR:02d}:{SLOT_MINUTE:02d}",
        }

    def run_once(self) -> Dict[str, Any]:
        return self._tick(reschedule=False)

    def _tick(self, reschedule: bool = True) -> Dict[str, Any]:
        result: Dict[str, Any] = {"ok": False}
        try:
            # Expired-recovery sweep first so the snapshot reflects recovered
            # grades (2026-08-11: 90.5% expired from rows retired on missing
            # price data; hydrate-on-miss now lets them re-grade).
            from internal.learning.expired_recovery import recover_expired_predictions

            recovery = recover_expired_predictions()
            result["recovered"] = recovery.get("recovered", 0)
            result["recovery_skipped"] = recovery.get("skipped", 0)

            from internal.learning.outcome_snapshot import run_snapshot

            payload = run_snapshot(save=True)
            result["ok"] = True
            result["alert_level"] = payload.get("alert_level")
            result["health_score"] = (payload.get("council_health") or {}).get("health_score")
            result["escalation"] = (payload.get("council_health") or {}).get("escalation")
            result["path"] = payload.get("path")
            if payload.get("alert_level") == "alert":
                logger.warning("outcome snapshot ALERT: %s", payload.get("alert_reasons"))
        except Exception as exc:
            result["error"] = str(exc)
            logger.warning("outcome snapshot tick failed: %s", exc)

        with _lock:
            self._last_result = dict(result)

        if reschedule and self._running:
            schedule_in_seconds(JOB_ID, self._tick, _interval_seconds())
        return result


def start_outcome_snapshot_scheduler(immediate: bool = False) -> Dict[str, Any]:
    if not _enabled():
        return {"started": False, "reason": "disabled"}
    global _scheduler
    with _lock:
        if _scheduler is None:
            _scheduler = OutcomeSnapshotScheduler()
        sched = _scheduler
    return sched.start(immediate=immediate)


def stop_outcome_snapshot_scheduler() -> Dict[str, Any]:
    global _scheduler
    with _lock:
        sched = _scheduler
        _scheduler = None
    if sched is None:
        return {"stopped": False, "reason": "not running"}
    return sched.stop()


def get_outcome_snapshot_scheduler_state() -> Dict[str, Any]:
    with _lock:
        return {
            "enabled": _enabled(),
            "scheduler": _scheduler.state() if _scheduler else {"running": False},
        }
