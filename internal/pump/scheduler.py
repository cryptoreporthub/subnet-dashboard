"""Boot + periodic pump ladder scanner (mirrors selector scheduler pattern)."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from internal.job_scheduler import cancel_job, schedule_in_seconds
from internal.pump.state import scan_all_subnets

logger = logging.getLogger(__name__)

PUMP_LADDER_REFRESH_MINUTES = int(os.environ.get("PUMP_LADDER_REFRESH_MINUTES", "20"))
PUMP_LADDER_RETRY_MINUTES = int(os.environ.get("PUMP_LADDER_RETRY_MINUTES", "3"))
JOB_ID = "pump-ladder-scheduler"

_scheduler: Optional["PumpLadderScheduler"] = None
_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _result_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if result.get("skipped"):
        out["skipped"] = result.get("skipped")
    for key in ("scanned", "transitions", "phase_counts", "soul_map"):
        if key in result:
            out[key] = result.get(key)
    return out


def _persist_scheduler_meta(
    run_at: str,
    ok: Optional[bool],
    error: Optional[str],
    last_result: Dict[str, Any],
) -> None:
    try:
        from internal.pump.state import load_state, save_state

        data = load_state()
        meta = data.setdefault("meta", {})
        meta["scheduler_last_run_at"] = run_at
        meta["scheduler_last_run_ok"] = ok
        meta["scheduler_last_run_error"] = error
        if last_result:
            meta["scheduler_last_result"] = last_result
        save_state(data)
    except Exception as exc:
        logger.debug("pump ladder scheduler meta persist failed: %s", exc)


def _read_persisted_scheduler_meta() -> Dict[str, Any]:
    try:
        from internal.pump.state import load_state

        meta = load_state().get("meta") or {}
        last_run_at = meta.get("scheduler_last_run_at") or meta.get("last_scan_at")
        last_result = meta.get("scheduler_last_result")
        if not isinstance(last_result, dict):
            last_result = {}
        if not last_result and meta.get("phase_counts"):
            last_result = {"phase_counts": meta.get("phase_counts")}
        return {
            "last_run_at": last_run_at,
            "last_run_ok": meta.get("scheduler_last_run_ok"),
            "last_run_error": meta.get("scheduler_last_run_error"),
            "last_result": last_result,
        }
    except Exception:
        return {}


def _needs_fast_retry(result: Dict[str, Any]) -> bool:
    if result.get("ok"):
        return False
    blob = " ".join(str(result.get(k) or "") for k in ("error", "skipped")).lower()
    needles = (
        "interpreter shutdown",
        "scan_in_progress",
        "heavy_job_busy",
        "no subnet signals",
    )
    return any(n in blob for n in needles)


def record_ladder_scan_run(
    result: Dict[str, Any],
    sched: Optional["PumpLadderScheduler"] = None,
) -> None:
    """Record any ladder scan (scheduler tick or kick) into volume meta + in-memory scheduler."""
    run_at = str(result.get("run_at") or _now_iso())
    ok = result.get("ok")
    error = result.get("error")
    last_result = _result_summary(result)
    _persist_scheduler_meta(run_at, ok, error, last_result)

    target = sched
    if target is None:
        with _lock:
            target = _scheduler
    if target is not None:
        target._apply_run_result(run_at, ok, error, last_result)


class PumpLadderScheduler:
    def __init__(self, refresh_minutes: int = PUMP_LADDER_REFRESH_MINUTES):
        self.refresh_minutes = refresh_minutes
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
        persisted = _read_persisted_scheduler_meta()
        if persisted.get("last_run_at"):
            self._apply_run_result(
                str(persisted["last_run_at"]),
                persisted.get("last_run_ok"),
                persisted.get("last_run_error"),
                persisted.get("last_result") or {},
            )
        if immediate:
            threading.Thread(target=self._tick, daemon=True).start()
        else:
            self._schedule(5)
        return {"started": True, "refresh_minutes": self.refresh_minutes}

    def stop(self) -> Dict[str, Any]:
        with _lock:
            self._running = False
        cancel_job(JOB_ID)
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

    def _apply_run_result(
        self,
        run_at: str,
        ok: Optional[bool],
        error: Optional[str],
        last_result: Dict[str, Any],
    ) -> None:
        with _lock:
            self._last_run_at = run_at
            self._last_ok = ok
            self._last_error = error
            self._last_result = last_result

    def run_once(self) -> Dict[str, Any]:
        return self._tick()

    def _schedule(self, minutes: int) -> None:
        with _lock:
            if not self._running:
                return
        schedule_in_seconds(JOB_ID, self._tick, minutes * 60)

    def _schedule_next(self, result: Dict[str, Any]) -> None:
        if _needs_fast_retry(result):
            self._schedule(PUMP_LADDER_RETRY_MINUTES)
        else:
            self._schedule(self.refresh_minutes)

    def _tick(self) -> Dict[str, Any]:
        from internal.heavy_job_gate import heavy_job_slot

        with heavy_job_slot("pump_ladder") as acquired:
            if not acquired:
                result = {"ok": True, "run_at": _now_iso(), "skipped": "heavy_job_busy"}
                record_ladder_scan_run(result, sched=self)
                self._schedule_next(result)
                return result
            return self._tick_body()

    def _tick_body(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {"ok": False, "run_at": _now_iso(), "error": None}
        try:
            scan = scan_all_subnets()
            result.update(scan)
            result["ok"] = bool(scan.get("ok"))
        except Exception as exc:
            result["error"] = str(exc)
            logger.warning("Pump ladder scan failed: %s", exc)

        if not result.get("ok"):
            record_ladder_scan_run(result, sched=self)

        self._schedule_next(result)
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
            base: Dict[str, Any] = {
                "running": False,
                "refresh_minutes": PUMP_LADDER_REFRESH_MINUTES,
            }
        else:
            base = _scheduler.state()

    persisted = _read_persisted_scheduler_meta()
    merged = dict(base)
    for key in ("last_run_at", "last_run_ok", "last_run_error", "last_result"):
        if merged.get(key) is None and persisted.get(key) is not None:
            merged[key] = persisted[key]
    if not merged.get("last_result"):
        merged["last_result"] = persisted.get("last_result") or {}
    return merged


def ensure_pump_ladder_scheduler(immediate: bool = False) -> Dict[str, Any]:
    """Idempotent start used by analytics/resolver boot hooks."""
    with _lock:
        if _scheduler is not None and _scheduler._running:
            return {"started": False, "reason": "already running"}
    return start_pump_ladder_scheduler(immediate=immediate)
