"""Traffic-independent daily + hour pick schedulers (Learning Loop Phase 1).

Creates today's daily pick and records the hour #1 pick on a timer so the
learning loop does not depend on homepage / top-pick traffic.

GET /api/daily-pick stays read-only — this module is the background author.
"""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from internal.job_scheduler import cancel_job, schedule_in_seconds
from internal.liveness import LivenessTracker, get_tracker

logger = logging.getLogger(__name__)

HOUR_PICK_TRACKER_NAME = "hour_pick"
DAILY_PICK_TRACKER_NAME = "daily_pick"

DAILY_JOB_ID = "daily-pick-scheduler"
HOUR_JOB_ID = "hour-pick-scheduler"

HOUR_PICK_REFRESH_MINUTES = int(os.environ.get("HOUR_PICK_REFRESH_MINUTES", "180"))
DAILY_PICK_SLOT_UTC_HOUR = int(os.environ.get("DAILY_PICK_SLOT_UTC_HOUR", "0"))
DAILY_PICK_SLOT_UTC_MINUTE = int(os.environ.get("DAILY_PICK_SLOT_UTC_MINUTE", "15"))
PICK_SCHEDULER_UNIVERSE_CAP = int(os.environ.get("PICK_SCHEDULER_UNIVERSE_CAP", "24"))
# ponytail: one failed cold-start/slot tick must not wait until tomorrow 00:15.
DAILY_PICK_RETRY_MINUTES = int(os.environ.get("DAILY_PICK_RETRY_MINUTES", "15"))
DAILY_PICK_TICK_TIMEOUT_SECONDS = int(os.environ.get("DAILY_PICK_TICK_TIMEOUT_SECONDS", "90"))
PICK_SCHEDULER_STATE_PATH = os.environ.get(
    "PICK_SCHEDULER_STATE_PATH", os.path.join("data", "pick_scheduler_state.json")
)

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


def _seconds_until_next_daily_tick(*, today_ready: bool) -> float:
    """Next-day slot when today is written; otherwise retry soon."""
    if today_ready:
        return _seconds_until_daily_slot()
    retry_m = max(1, min(DAILY_PICK_RETRY_MINUTES, 120))
    return float(retry_m * 60)


def _today_pick_ready() -> bool:
    """True when today's record is a finished decision (not a scheduler_hold placeholder)."""
    try:
        from internal.council.daily_pick_engine import _find_today, _load

        rec = _find_today(_load())
        if not isinstance(rec, dict):
            return False
        if rec.get("scheduler_hold"):
            return False
        return True
    except Exception:
        return False


def _write_scheduler_state(
    extra: Optional[Dict[str, Any]] = None, *, trigger: str = "daily_pick_tick"
) -> None:
    """Volume file so web /api/learning/health can see worker scheduler status."""
    from internal.ops.mutation_log import log_mutation

    writer = "_write_scheduler_state"
    path = PICK_SCHEDULER_STATE_PATH
    log_mutation(
        operation="start", path=path, writer_function=writer, trigger=trigger
    )
    try:
        payload = get_pick_scheduler_state()
        if extra:
            payload = {**payload, **extra}
        payload["written_at"] = _now_iso()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        import json

        log_mutation(
            operation="temp-write",
            path=path,
            writer_function=writer,
            trigger=trigger,
        )
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        log_mutation(
            operation="rename", path=path, writer_function=writer, trigger=trigger
        )
        os.replace(tmp, path)
        log_mutation(
            operation="completed",
            path=path,
            writer_function=writer,
            trigger=trigger,
        )
    except Exception as exc:
        log_mutation(
            operation="failed", path=path, writer_function=writer, trigger=trigger
        )
        logger.warning("pick scheduler state write failed: %s", exc)


def load_pick_scheduler_state_file() -> Optional[Dict[str, Any]]:
    try:
        import json

        with open(PICK_SCHEDULER_STATE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


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
        from internal.learning.prediction_loop import record_hold_decision, record_pick_prediction

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

        if str(pick.get("action") or "").upper() == "HOLD":
            record_hold_decision(
                candidate=pick,
                reason=pick.get("hold_reason") or pick.get("reason"),
                horizon_type="hour",
                subnet=subnet_row or None,
                market_context=market_context,
            )
            return

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


def _record_ab_benchmark(subnets: Any, market_context: Dict[str, Any], source: str) -> Optional[str]:
    """Capture one dynamic-ranking observation without making it request-driven."""
    try:
        from internal.council.ab_benchmark import record_snapshot, settle_due_snapshots

        settle_due_snapshots(subnets)
        snapshot = record_snapshot(subnets, market_context, source=source)
        return str(snapshot.get("observation_slot") or snapshot.get("captured_at") or "")
    except Exception as exc:
        logger.warning("A/B benchmark snapshot failed: %s", exc)
        return None


class DailyPickScheduler:
    def __init__(self) -> None:
        self._last_result: Dict[str, Any] = {}
        self._work_lock = threading.Lock()
        # ponytail: timeout abandons in-flight work via generation bump; orphan
        # threads may still finish in the background but cannot commit results.
        self._work_generation = 0
        retry_seconds = max(1, min(DAILY_PICK_RETRY_MINUTES, 120)) * 60
        self.liveness = LivenessTracker(
            name=DAILY_PICK_TRACKER_NAME,
            interval_seconds=max(retry_seconds, 3600),
            staleness_factor=2,
            persist=True,
        )

    def start(self, immediate: bool = False) -> Dict[str, Any]:
        with _lock:
            already = (
                _daily is self and self.liveness.snapshot().get("lifecycle") == "started"
            )
        self.liveness.start()
        if immediate:
            threading.Thread(target=self._tick, daemon=True, name="daily-pick-tick").start()
        else:
            # Cold start: create today soon, then align to UTC slot.
            # Persisted lifecycle=started is not proof a DateTrigger is armed
            # (new process generation after prior boot).
            schedule_in_seconds(DAILY_JOB_ID, self._tick, 45)
        if already:
            return {"started": False, "reason": "already running"}
        return {"started": True, "job": DAILY_JOB_ID}

    def stop(self) -> Dict[str, Any]:
        cancel_job(DAILY_JOB_ID)
        return {"stopped": True}

    def state(self) -> Dict[str, Any]:
        snap = self.liveness.snapshot()
        last_result = self._last_result
        if not last_result and isinstance(snap.get("last_evidence"), dict):
            ev = snap["last_evidence"]
            last_result = {
                k: ev.get(k)
                for k in ("action", "date", "netuid", "scheduler_hold")
                if k in ev
            }
        return {
            "last_run_at": snap.get("last_event_at"),
            "last_run_error": snap.get("last_error"),
            "last_result": last_result,
            "slot_utc": f"{DAILY_PICK_SLOT_UTC_HOUR:02d}:{DAILY_PICK_SLOT_UTC_MINUTE:02d}",
            "lifecycle": snap.get("lifecycle"),
            "status": snap.get("status"),
            "last_success_at": snap.get("last_success_at"),
            "success_age_seconds": snap.get("success_age_seconds"),
            "liveness": snap,
        }

    def run_once(self) -> Dict[str, Any]:
        return self._tick(reschedule=False)

    def _tick(self, reschedule: bool = True) -> Dict[str, Any]:
        result: Dict[str, Any] = {"ok": False, "run_at": _now_iso(), "error": None}
        today_ready = False
        try:
            from internal.council.daily_pick_engine import get_or_create_today_pick

            subnets = _load_capped_subnets()
            ctx = _market_context(subnets)
            timeout = max(5, min(DAILY_PICK_TICK_TIMEOUT_SECONDS, 600))
            payload = None
            with self._work_lock:
                self._work_generation += 1
                tick_generation = self._work_generation

            pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="daily-pick-work")

            def _run_pick() -> Optional[Dict[str, Any]]:
                out = get_or_create_today_pick(subnets, ctx, False)
                with self._work_lock:
                    if tick_generation != self._work_generation:
                        return None
                return out

            try:
                fut = pool.submit(_run_pick)
                payload = fut.result(timeout=timeout)
            except FuturesTimeoutError:
                with self._work_lock:
                    self._work_generation += 1
                result["error"] = f"daily pick tick timed out after {timeout}s"
                logger.warning("%s (worker abandoned)", result["error"])
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
            tick_succeeded = isinstance(payload, dict)
            if tick_succeeded:
                result["ok"] = True
                result["action"] = payload.get("action")
                result["date"] = payload.get("date")
                pick = payload.get("pick")
                if isinstance(pick, dict):
                    sn = pick.get("subnet") if isinstance(pick.get("subnet"), dict) else {}
                    result["netuid"] = pick.get("netuid") or sn.get("netuid")
                result["ab_benchmark"] = _record_ab_benchmark(
                    subnets, ctx, "daily-pick-scheduler"
                )
                today_ready = _today_pick_ready()
            else:
                # ponytail: timeout/error ticks must retry soon — abandoned worker
                # writes to disk must not defer scheduling to tomorrow's UTC slot.
                today_ready = False
            if not today_ready and result.get("error"):
                try:
                    from internal.council.daily_pick_engine import write_scheduler_hold

                    hold = write_scheduler_hold(str(result["error"]))
                    result["scheduler_hold"] = True
                    result["action"] = hold.get("action")
                    result["date"] = hold.get("date")
                except Exception as hold_exc:
                    logger.warning("scheduler hold write failed: %s", hold_exc)
            elif result["ok"] and not today_ready:
                # Placeholder HOLD still counts as progress for GET, but keep retrying.
                result["error"] = result.get("error") or "today pick not ready (scheduler_hold)"
        except Exception as exc:
            result["error"] = str(exc)
            logger.warning("daily pick scheduler tick failed: %s", exc)
            today_ready = False
            if not _today_pick_ready():
                try:
                    from internal.council.daily_pick_engine import write_scheduler_hold

                    write_scheduler_hold(str(exc))
                    result["scheduler_hold"] = True
                except Exception as hold_exc:
                    logger.warning("scheduler hold write failed: %s", hold_exc)

        tick_ok = bool(result.get("ok")) and today_ready
        evidence: Dict[str, Any] = {
            "op": "daily_pick",
            "action": result.get("action"),
            "date": result.get("date"),
            "netuid": result.get("netuid"),
            "today_ready": today_ready,
        }
        if result.get("scheduler_hold"):
            evidence["scheduler_hold"] = True
        if tick_ok:
            self.liveness.record_success(evidence=evidence)
        else:
            self.liveness.record_failure(error=str(result.get("error") or "today pick not ready"))

        with _lock:
            self._last_result = {
                k: result.get(k)
                for k in ("action", "date", "netuid", "scheduler_hold")
                if k in result
            }
            still_scheduled = _daily is self

        if still_scheduled:
            delay = _seconds_until_next_daily_tick(today_ready=today_ready)
            schedule_in_seconds(DAILY_JOB_ID, self._tick, delay)
            result["next_delay_seconds"] = delay
            result["today_ready"] = today_ready
        _write_scheduler_state({"last_tick": result})
        return result


class HourPickScheduler:
    def __init__(self, refresh_minutes: int = HOUR_PICK_REFRESH_MINUTES) -> None:
        self.refresh_minutes = max(15, min(int(refresh_minutes), 24 * 60))
        self._last_result: Dict[str, Any] = {}
        self.liveness = LivenessTracker(
            name=HOUR_PICK_TRACKER_NAME,
            interval_seconds=self.refresh_minutes * 60,
            staleness_factor=2,
            persist=True,
        )

    def start(self, immediate: bool = False) -> Dict[str, Any]:
        with _lock:
            already = (
                _hour is self and self.liveness.snapshot().get("lifecycle") == "started"
            )
        self.liveness.start()
        if immediate:
            threading.Thread(target=self._tick, daemon=True, name="hour-pick-tick").start()
        else:
            # Persisted lifecycle=started is not proof a DateTrigger is armed.
            schedule_in_seconds(HOUR_JOB_ID, self._tick, 90)
        if already:
            return {"started": False, "reason": "already running"}
        return {"started": True, "refresh_minutes": self.refresh_minutes}

    def stop(self) -> Dict[str, Any]:
        cancel_job(HOUR_JOB_ID)
        return {"stopped": True}

    def state(self) -> Dict[str, Any]:
        snap = self.liveness.snapshot()
        return {
            "refresh_minutes": self.refresh_minutes,
            "last_run_at": snap.get("last_event_at"),
            "last_run_error": snap.get("last_error"),
            "last_result": self._last_result,
            "lifecycle": snap.get("lifecycle"),
            "status": snap.get("status"),
            "last_success_at": snap.get("last_success_at"),
            "success_age_seconds": snap.get("success_age_seconds"),
            "liveness": snap,
        }

    def run_once(self) -> Dict[str, Any]:
        return self._tick(reschedule=False)

    def _tick(self, reschedule: bool = True) -> Dict[str, Any]:
        result: Dict[str, Any] = {"ok": False, "run_at": _now_iso(), "error": None}
        try:
            from internal.council.hourly_pick import select_hourly_pick

            subnets = _load_capped_subnets()
            ctx = _market_context(subnets)
            result["ab_benchmark"] = _record_ab_benchmark(
                subnets, ctx, "hour-pick-scheduler"
            )
            pick = select_hourly_pick(subnets, ctx)
            _record_hour_pick(pick if isinstance(pick, dict) else {}, subnets, ctx)
            result["ok"] = True
            sn = (pick or {}).get("subnet") if isinstance(pick, dict) else {}
            if isinstance(sn, dict):
                result["netuid"] = sn.get("netuid")
            if isinstance(pick, dict):
                result["final_confidence"] = pick.get("final_confidence")
            evidence: Dict[str, Any] = {"op": "hour_pick"}
            if result.get("netuid") is not None:
                evidence["netuid"] = result["netuid"]
            else:
                evidence["noop"] = True
            self.liveness.record_success(evidence=evidence)
        except Exception as exc:
            result["error"] = str(exc)
            self.liveness.record_failure(error=str(exc))
            logger.warning("hour pick scheduler tick failed: %s", exc)

        with _lock:
            self._last_result = {
                k: result.get(k) for k in ("netuid", "final_confidence") if k in result
            }
            still_scheduled = _hour is self

        if still_scheduled:
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


def _hour_state_from_tracker() -> Dict[str, Any]:
    """Persisted worker truth when web has no in-process hour scheduler."""
    refresh_m = max(15, min(HOUR_PICK_REFRESH_MINUTES, 24 * 60))
    tracker = get_tracker(HOUR_PICK_TRACKER_NAME)
    if tracker is None:
        tracker = LivenessTracker(
            name=HOUR_PICK_TRACKER_NAME,
            interval_seconds=refresh_m * 60,
            staleness_factor=2,
            persist=True,
        )
    snap = tracker.snapshot()
    last_result = snap.get("last_evidence") if isinstance(snap.get("last_evidence"), dict) else {}
    return {
        "refresh_minutes": refresh_m,
        "last_run_at": snap.get("last_event_at"),
        "last_run_error": snap.get("last_error"),
        "last_result": last_result,
        "lifecycle": snap.get("lifecycle"),
        "status": snap.get("status"),
        "last_success_at": snap.get("last_success_at"),
        "success_age_seconds": snap.get("success_age_seconds"),
        "liveness": snap,
        "source": snap.get("source"),
    }


def _daily_state_from_tracker() -> Dict[str, Any]:
    """Persisted worker truth when web has no in-process daily scheduler."""
    retry_seconds = max(1, min(DAILY_PICK_RETRY_MINUTES, 120)) * 60
    tracker = get_tracker(DAILY_PICK_TRACKER_NAME)
    if tracker is None:
        tracker = LivenessTracker(
            name=DAILY_PICK_TRACKER_NAME,
            interval_seconds=max(retry_seconds, 3600),
            staleness_factor=2,
            persist=True,
        )
    snap = tracker.snapshot()
    last_evidence = snap.get("last_evidence") if isinstance(snap.get("last_evidence"), dict) else {}
    last_result = {
        k: last_evidence.get(k)
        for k in ("action", "date", "netuid", "scheduler_hold")
        if k in last_evidence
    }
    return {
        "last_run_at": snap.get("last_event_at"),
        "last_run_error": snap.get("last_error"),
        "last_result": last_result,
        "slot_utc": f"{DAILY_PICK_SLOT_UTC_HOUR:02d}:{DAILY_PICK_SLOT_UTC_MINUTE:02d}",
        "lifecycle": snap.get("lifecycle"),
        "status": snap.get("status"),
        "last_success_at": snap.get("last_success_at"),
        "success_age_seconds": snap.get("success_age_seconds"),
        "liveness": snap,
        "source": snap.get("source"),
    }


def get_pick_scheduler_state() -> Dict[str, Any]:
    with _lock:
        daily_local = _daily.state() if _daily is not None else None
        hour_local = _hour.state() if _hour is not None else None
    daily_state = daily_local if daily_local is not None else _daily_state_from_tracker()
    hour_state = hour_local if hour_local is not None else _hour_state_from_tracker()
    return {
        "enabled": _enabled(),
        "daily": daily_state,
        "hour": hour_state,
    }
