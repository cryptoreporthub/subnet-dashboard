"""Periodic pump desk snapshot on inline worker (replaces Ditto 15m fetch)."""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Dict, Optional

from internal.job_scheduler import cancel_job, schedule_interval_seconds
from internal.liveness import LivenessTracker

logger = logging.getLogger(__name__)

JOB_ID = "pump-desk-snapshot"
INTERVAL_MINUTES = int(os.environ.get("PUMP_DESK_SNAPSHOT_MINUTES", "15"))
SNAPSHOT_TIMEOUT_SECONDS = max(
    1, int(os.environ.get("PUMP_DESK_SNAPSHOT_TIMEOUT_SECONDS", "120"))
)

_lock = threading.Lock()
_cycle_lock = threading.Lock()
_scheduler: Optional["PumpDeskSnapshotScheduler"] = None


def _enabled() -> bool:
    return os.environ.get("PUMP_DESK_SNAPSHOT_ENABLED", "on").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _stopped_scheduler_state() -> Dict[str, Any]:
    snap: Dict[str, Any] = {}
    try:
        from internal.liveness import get_tracker

        t = get_tracker("pump_desk_snapshot")
        if t is not None:
            snap = t.snapshot()
    except Exception:
        pass
    return {
        "running": False,
        "interval_minutes": INTERVAL_MINUTES,
        "last_result": {},
        "liveness": snap,
    }


class PumpDeskSnapshotScheduler:
    def __init__(self, interval_minutes: int = INTERVAL_MINUTES) -> None:
        self.interval_minutes = max(5, min(int(interval_minutes), 60))
        self._last_result: Dict[str, Any] = {}
        self._active = False
        self.liveness = LivenessTracker(
            name="pump_desk_snapshot",
            interval_seconds=max(60, self.interval_minutes * 60),
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
        if self._active:
            return {"started": False, "reason": "already running"}
        delay = 30 if immediate else max(60, self.interval_minutes * 60)
        self._active = True
        try:
            schedule_interval_seconds(
                JOB_ID,
                self._tick,
                self.interval_minutes * 60,
                start_delay_seconds=delay,
            )
        except Exception as exc:
            self._active = False
            self.liveness.record_failure(error=f"schedule_failed: {exc}")
            return {"started": False, "reason": "schedule_failed", "error": str(exc)}
        self.liveness.start()
        return {"started": True, "interval_minutes": self.interval_minutes}

    def stop(self) -> Dict[str, Any]:
        self._active = False
        cancel_job(JOB_ID)
        return {"stopped": True}

    def state(self) -> Dict[str, Any]:
        snap = self.liveness.snapshot()
        return {
            "running": self._active,
            "interval_minutes": self.interval_minutes,
            "last_result": self._last_result,
            "liveness": snap,
        }

    def run_once(self) -> Dict[str, Any]:
        return self._tick()

    def _run_snapshot_with_timeout(self) -> Dict[str, Any]:
        if not _cycle_lock.acquire(blocking=False):
            return {"ok": False, "skipped": "cycle_in_flight"}

        pool = ThreadPoolExecutor(max_workers=1)
        submitted = False

        def _run() -> Dict[str, Any]:
            try:
                from internal.pump.desk_snapshot import run_snapshot

                return run_snapshot(save=True)
            finally:
                _cycle_lock.release()

        try:
            future = pool.submit(_run)
            submitted = True
            try:
                return future.result(timeout=SNAPSHOT_TIMEOUT_SECONDS)
            except FuturesTimeoutError:
                return {
                    "ok": False,
                    "error": f"cycle_timeout_{SNAPSHOT_TIMEOUT_SECONDS}s",
                }
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
            if not submitted:
                _cycle_lock.release()

    def _tick(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"ok": False}
        try:
            payload = self._run_snapshot_with_timeout()
            if payload.get("skipped"):
                result["skipped"] = payload["skipped"]
                self.liveness.record_skip(reason=str(payload["skipped"]))
            elif payload.get("error"):
                result["error"] = str(payload["error"])
                self.liveness.record_failure(error=result["error"])
            else:
                result["ok"] = True
                result["alert_level"] = payload.get("alert_level")
                result["path"] = payload.get("path")
                result["actionable_count"] = len(payload.get("actionable_badges") or [])
                self.liveness.record_success(
                    evidence={
                        "actionable_count": result["actionable_count"],
                        "op": "pump_desk_snapshot",
                    }
                )
                if payload.get("alert_level") == "alert":
                    logger.warning(
                        "pump desk snapshot ALERT: %s",
                        payload.get("alert_reasons"),
                    )
        except Exception as exc:
            result["error"] = str(exc)
            self.liveness.record_failure(error=str(exc))
            logger.warning("pump desk snapshot tick failed: %s", exc)

        with _lock:
            self._last_result = dict(result)
        return result


def start_pump_desk_snapshot_scheduler(immediate: bool = False) -> Dict[str, Any]:
    if not _enabled():
        return {"started": False, "reason": "disabled"}
    global _scheduler
    with _lock:
        if _scheduler is not None:
            if _scheduler._active:
                return {"started": False, "reason": "already running"}
        else:
            _scheduler = PumpDeskSnapshotScheduler()
    return _scheduler.start(immediate=immediate)


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
            "scheduler": _scheduler.state() if _scheduler else _stopped_scheduler_state(),
        }
