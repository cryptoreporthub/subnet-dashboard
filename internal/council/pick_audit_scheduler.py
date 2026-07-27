"""Nightly pick selection audit scheduler (evidence loop on worker)."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from internal.job_scheduler import cancel_job, schedule_in_seconds

logger = logging.getLogger(__name__)

JOB_ID = "pick-selection-audit"
AUDIT_UTC_HOUR = int(os.environ.get("PICK_AUDIT_SLOT_UTC_HOUR", "23"))
AUDIT_UTC_MINUTE = int(os.environ.get("PICK_AUDIT_SLOT_UTC_MINUTE", "45"))

_lock = threading.Lock()
_scheduler: Optional["PickSelectionAuditScheduler"] = None


def _enabled() -> bool:
    return os.environ.get("PICK_AUDIT_ENABLED", "on").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _seconds_until_slot() -> float:
    now = datetime.now(timezone.utc)
    target = now.replace(
        hour=max(0, min(23, AUDIT_UTC_HOUR)),
        minute=max(0, min(59, AUDIT_UTC_MINUTE)),
        second=0,
        microsecond=0,
    )
    if target <= now:
        target = target + timedelta(days=1)
    return max(30.0, (target - now).total_seconds())


def _load_subnets_and_context() -> tuple[list, dict]:
    try:
        from server import _get_subnets_with_source, _market_context_with_weights

        subnets, _ = _get_subnets_with_source()
        ctx = _market_context_with_weights(subnets or [])
        return subnets or [], ctx
    except Exception as exc:
        logger.warning("pick audit subnet load failed: %s", exc)
        return [], {}


class PickSelectionAuditScheduler:
    def __init__(self) -> None:
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
            threading.Thread(target=self._tick, daemon=True, name="pick-audit-tick").start()
        else:
            schedule_in_seconds(JOB_ID, self._tick, _seconds_until_slot())
        return {"started": True, "job": JOB_ID, "slot_utc": f"{AUDIT_UTC_HOUR:02d}:{AUDIT_UTC_MINUTE:02d}"}

    def stop(self) -> Dict[str, Any]:
        with _lock:
            self._running = False
        cancel_job(JOB_ID)
        return {"stopped": True}

    def state(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "last_run_at": self._last_run_at,
            "last_run_ok": self._last_ok,
            "last_run_error": self._last_error,
            "last_result": self._last_result,
            "slot_utc": f"{AUDIT_UTC_HOUR:02d}:{AUDIT_UTC_MINUTE:02d}",
        }

    def run_once(self) -> Dict[str, Any]:
        return self._tick(reschedule=False)

    def _tick(self, reschedule: bool = True) -> Dict[str, Any]:
        result: Dict[str, Any] = {"ok": False, "run_at": _now_iso(), "error": None}
        try:
            from internal.council.pick_selection_audit import run_audit_today

            subnets, ctx = _load_subnets_and_context()
            payload = run_audit_today(subnets, ctx, save=True)
            result["ok"] = True
            result["verdict"] = payload.get("verdict")
            result["category"] = payload.get("category")
            result["published_netuid"] = payload.get("published_netuid")
            primary = (payload.get("oracles") or {}).get("scheduler_cap_24", {})
            result["oracle_scheduler_netuid"] = (primary.get("pick") or {}).get("netuid")
            result["audit_path"] = payload.get("pick_date")
            if payload.get("verdict") == "MISS":
                logger.warning(
                    "pick selection audit MISS: category=%s published=%s oracle=%s",
                    payload.get("category"),
                    payload.get("published_netuid"),
                    result.get("oracle_scheduler_netuid"),
                )
        except Exception as exc:
            result["error"] = str(exc)
            logger.warning("pick selection audit tick failed: %s", exc)

        with _lock:
            self._last_run_at = result["run_at"]
            self._last_ok = result.get("ok")
            self._last_error = result.get("error")
            self._last_result = {
                k: result.get(k)
                for k in (
                    "verdict",
                    "category",
                    "published_netuid",
                    "oracle_scheduler_netuid",
                )
                if k in result
            }

        if reschedule and self._running:
            schedule_in_seconds(JOB_ID, self._tick, _seconds_until_slot())
        return result


def start_pick_audit_scheduler(immediate: bool = False) -> Dict[str, Any]:
    if not _enabled():
        return {"started": False, "reason": "disabled"}
    global _scheduler
    with _lock:
        if _scheduler is None:
            _scheduler = PickSelectionAuditScheduler()
        sched = _scheduler
    return sched.start(immediate=immediate)


def stop_pick_audit_scheduler() -> Dict[str, Any]:
    global _scheduler
    with _lock:
        sched = _scheduler
        _scheduler = None
    if sched is None:
        return {"stopped": False, "reason": "not running"}
    return sched.stop()


def get_pick_audit_scheduler_state() -> Dict[str, Any]:
    with _lock:
        return {
            "enabled": _enabled(),
            "scheduler": _scheduler.state() if _scheduler else {"running": False},
        }
