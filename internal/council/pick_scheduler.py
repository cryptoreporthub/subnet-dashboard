"""Traffic-independent daily + hour pick schedulers (Learning Loop Phase 1).

Creates today's daily pick and records the hour #1 pick on a timer so the
learning loop does not depend on homepage / top-pick traffic.

GET /api/daily-pick stays read-only — this module is the background author.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from internal.job_scheduler import cancel_job, schedule_in_seconds

logger = logging.getLogger(__name__)

DAILY_JOB_ID = "daily-pick-scheduler"
HOUR_JOB_ID = "hour-pick-scheduler"

HOUR_PICK_REFRESH_MINUTES = int(os.environ.get("HOUR_PICK_REFRESH_MINUTES", "180"))
DAILY_PICK_SLOT_UTC_HOUR = int(os.environ.get("DAILY_PICK_SLOT_UTC_HOUR", "0"))
DAILY_PICK_SLOT_UTC_MINUTE = int(os.environ.get("DAILY_PICK_SLOT_UTC_MINUTE", "15"))
PICK_SCHEDULER_UNIVERSE_CAP = int(os.environ.get("PICK_SCHEDULER_UNIVERSE_CAP", "24"))

_lock = threading.Lock()
_daily: Optional["DailyPickScheduler"] = None
_hour: Optional["HourPickScheduler"] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _enabled() -> bool:
    return os.environ.get("PICK_SCHEDULER_ENABLED", "on").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _seconds_until_daily_slot() -> float:
    """Seconds until next DAILY_PICK_SLOT_UTC_* (at least 30s)."""
    now = datetime.now(timezone.utc)
    target = now.replace(
        hour=max(0, min(23, DAILY_PICK_SLOT_UTC_HOUR)),
        minute=max(0, min(59, DAILY_PICK_SLOT_UTC_MINUTE)),
        second=0,
        microsecond=0,
    )
    if target <= now:
        target = target + timedelta(days=1)
    return max(30.0, (target - now).total_seconds())


def _load_capped_subnets() -> Any:
    """Lazy subnet snapshot capped for Fly safety (never full 127 here)."""
    try:
        from server import TOP_SCORING_UNIVERSE, _cap_subnets_for_scoring, _get_subnets_with_source

        subnets, _ = _get_subnets_with_source()
        cap = min(PICK_SCHEDULER_UNIVERSE_CAP, TOP_SCORING_UNIVERSE)
        return _cap_subnets_for_scoring(subnets or [], limit=cap)
    except Exception as exc:
        logger.warning("pick scheduler subnet load failed: %s", exc)
        return []


def _market_context(subnets: Any) -> Dict[str, Any]:
    try:
        from server import _market_context_with_weights

        return _market_context_with_weights(subnets or [])
    except Exception:
        return {}


def _record_hour_pick(pick: Dict[str, Any], subnets: Any, market_context: Dict[str, Any]) -> None:
    if not pick:
        return
    try:
        from internal.council import pick_history
        from internal.learning.prediction_loop import record_pick_prediction

        netuid = None
        sn = pick.get("subnet") if isinstance(pick.get("subnet"), dict) else {}
        if sn:
            netuid = sn.get("netuid")
        subnet_row = next(
            (s for s in (subnets or []) if isinstance(s, dict) and s.get("netuid") == netuid),
            None,
        )
        if not subnet_row:
            subnet_row = dict(sn) if sn else {}
            if netuid is not None:
                subnet_row.setdefault("netuid", netuid)
        if float(subnet_row.get("price", 0) or 0) <= 0:
            return
        stored = record_pick_prediction(
            pick,
            subnet_row,
            horizon_type="hour",
            market_context=market_context,
        )
        if stored:
            try:
                pick_history.record_hour_pick(
                    pick, subnet_row, prediction_id=stored.get("id")
                )
            except Exception as exc:
                logger.warning("pick_history record failed: %s", exc)
    except Exception as exc:
        logger.warning("hour pick learning record failed: %s", exc)


class DailyPickScheduler:
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
            threading.Thread(target=self._tick, daemon=True, name="daily-pick-tick").start()
        else:
            # Cold start: create today soon, then align to UTC slot.
            schedule_in_seconds(DAILY_JOB_ID, self._tick, 45)
        return {"started": True, "job": DAILY_JOB_ID}

    def stop(self) -> Dict[str, Any]:
        with _lock:
            self._running = False
        cancel_job(DAILY_JOB_ID)
        return {"stopped": True}

    def state(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "last_run_at": self._last_run_at,
            "last_run_ok": self._last_ok,
            "last_run_error": self._last_error,
            "last_result": self._last_result,
            "slot_utc": f"{DAILY_PICK_SLOT_UTC_HOUR:02d}:{DAILY_PICK_SLOT_UTC_MINUTE:02d}",
        }

    def run_once(self) -> Dict[str, Any]:
        return self._tick(reschedule=False)

    def _tick(self, reschedule: bool = True) -> Dict[str, Any]:
        result: Dict[str, Any] = {"ok": False, "run_at": _now_iso(), "error": None}
        try:
            from internal.council.daily_pick_engine import get_or_create_today_pick

            subnets = _load_capped_subnets()
            ctx = _market_context(subnets)
            payload = get_or_create_today_pick(subnets, ctx, force=False)
            result["ok"] = True
            result["action"] = payload.get("action") if isinstance(payload, dict) else None
            result["date"] = payload.get("date") if isinstance(payload, dict) else None
            pick = payload.get("pick") if isinstance(payload, dict) else None
            if isinstance(pick, dict):
                sn = pick.get("subnet") if isinstance(pick.get("subnet"), dict) else {}
                result["netuid"] = pick.get("netuid") or sn.get("netuid")
        except Exception as exc:
            result["error"] = str(exc)
            logger.warning("daily pick scheduler tick failed: %s", exc)

        with _lock:
            self._last_run_at = result["run_at"]
            self._last_ok = result.get("ok")
            self._last_error = result.get("error")
            self._last_result = {
                k: result.get(k) for k in ("action", "date", "netuid") if k in result
            }

        if reschedule and self._running:
            schedule_in_seconds(DAILY_JOB_ID, self._tick, _seconds_until_daily_slot())
        return result


class HourPickScheduler:
    def __init__(self, refresh_minutes: int = HOUR_PICK_REFRESH_MINUTES) -> None:
        self.refresh_minutes = max(15, min(int(refresh_minutes), 24 * 60))
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
            threading.Thread(target=self._tick, daemon=True, name="hour-pick-tick").start()
        else:
            schedule_in_seconds(HOUR_JOB_ID, self._tick, 90)
        return {"started": True, "refresh_minutes": self.refresh_minutes}

    def stop(self) -> Dict[str, Any]:
        with _lock:
            self._running = False
        cancel_job(HOUR_JOB_ID)
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
        return self._tick(reschedule=False)

    def _tick(self, reschedule: bool = True) -> Dict[str, Any]:
        result: Dict[str, Any] = {"ok": False, "run_at": _now_iso(), "error": None}
        try:
            from internal.council.hourly_pick import select_hourly_pick

            subnets = _load_capped_subnets()
            ctx = _market_context(subnets)
            pick = select_hourly_pick(subnets, ctx)
            _record_hour_pick(pick if isinstance(pick, dict) else {}, subnets, ctx)
            result["ok"] = True
            sn = (pick or {}).get("subnet") if isinstance(pick, dict) else {}
            if isinstance(sn, dict):
                result["netuid"] = sn.get("netuid")
            if isinstance(pick, dict):
                result["final_confidence"] = pick.get("final_confidence")
        except Exception as exc:
            result["error"] = str(exc)
            logger.warning("hour pick scheduler tick failed: %s", exc)

        with _lock:
            self._last_run_at = result["run_at"]
            self._last_ok = result.get("ok")
            self._last_error = result.get("error")
            self._last_result = {
                k: result.get(k) for k in ("netuid", "final_confidence") if k in result
            }

        if reschedule and self._running:
            schedule_in_seconds(HOUR_JOB_ID, self._tick, self.refresh_minutes * 60)
        return result


def start_pick_schedulers(immediate: bool = False) -> Dict[str, Any]:
    if not _enabled():
        return {"started": False, "reason": "disabled"}
    global _daily, _hour
    with _lock:
        if _daily is None:
            _daily = DailyPickScheduler()
        if _hour is None:
            _hour = HourPickScheduler()
        daily, hour = _daily, _hour
    return {
        "started": True,
        "daily": daily.start(immediate=immediate),
        "hour": hour.start(immediate=immediate),
    }


def stop_pick_schedulers() -> Dict[str, Any]:
    global _daily, _hour
    with _lock:
        daily, hour = _daily, _hour
        _daily = None
        _hour = None
    out: Dict[str, Any] = {}
    if daily is not None:
        out["daily"] = daily.stop()
    if hour is not None:
        out["hour"] = hour.stop()
    return out or {"stopped": False, "reason": "not running"}


def get_pick_scheduler_state() -> Dict[str, Any]:
    with _lock:
        return {
            "enabled": _enabled(),
            "daily": _daily.state() if _daily else {"running": False},
            "hour": _hour.state() if _hour else {"running": False},
        }
