"""Shared APScheduler BackgroundScheduler for Fly single-worker background jobs."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

_scheduler: Optional[BackgroundScheduler] = None
_shutting_down = False
_lock = threading.Lock()

logger = logging.getLogger(__name__)

# Zombie-loop guard: a one-shot scheduled tick (e.g. the resolver self
# re-arm via schedule_in_seconds) silently dies forever if the tick raises
# anything other than the handled timeout. Wrap every scheduled func so a
# failure is logged, surfaced in state() and retried with a bounded cap
# instead of killing the loop. Interval jobs are self-healing and only get
# the logging wrapper.
_JOB_RETRY_SECONDS = int(os.environ.get("JOB_RETRY_SECONDS", "60"))
_JOB_RETRY_CAP = int(os.environ.get("JOB_RETRY_CAP", "5"))
_retry_counts: Dict[str, int] = {}


def _guarded(job_id: str, func: Callable[[], None], retryable: bool) -> Callable[[], None]:
    """Wrap a scheduled func: log failures; reschedule one-shot jobs on error."""

    def _run() -> None:
        try:
            func()
            _retry_counts.pop(job_id, None)
        except Exception as exc:
            logger.exception("background job %s failed: %s", job_id, exc)
            _retry_counts[job_id] = _retry_counts.get(job_id, 0) + 1
            if not retryable or _shutting_down:
                return
            if _retry_counts[job_id] > _JOB_RETRY_CAP:
                logger.error(
                    "background job %s gave up after %d consecutive failures",
                    job_id, _retry_counts[job_id],
                )
                _retry_counts.pop(job_id, None)
                return
            try:
                schedule_in_seconds(
                    f"{job_id}:retry", func, _JOB_RETRY_SECONDS, replace_existing=False
                )
            except Exception:
                pass

    return _run


def get_background_scheduler() -> BackgroundScheduler:
    """Return the process-wide background scheduler, starting it on first use."""
    global _scheduler
    with _lock:
        if _shutting_down:
            raise RuntimeError("background scheduler is shut down")
        if _scheduler is None:
            sched = BackgroundScheduler(daemon=True)
            sched.start()
            _scheduler = sched
        return _scheduler


def schedule_interval_seconds(
    job_id: str,
    func: Callable[[], None],
    seconds: float,
    *,
    replace_existing: bool = True,
    start_delay_seconds: float = 0,
) -> None:
    """Run ``func`` on a fixed interval."""
    if _shutting_down:
        return
    sched = get_background_scheduler()
    start = datetime.now(timezone.utc) + timedelta(seconds=start_delay_seconds)
    sched.add_job(
        _guarded(job_id, func, retryable=False),
        IntervalTrigger(seconds=seconds, start_date=start),
        id=job_id,
        replace_existing=replace_existing,
    )


def schedule_in_seconds(
    job_id: str,
    func: Callable[[], None],
    seconds: float,
    *,
    replace_existing: bool = True,
    misfire_grace_time: Optional[int] = None,
) -> None:
    """Run ``func`` once after ``seconds``.

    ``misfire_grace_time`` overrides APScheduler's 1s default. Daily-pick
    retries pass 60s so a GIL-late DateTrigger is not silently dropped.
    """
    if _shutting_down:
        return
    sched = get_background_scheduler()
    run_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    kwargs: Dict[str, Any] = {
        "id": job_id,
        "replace_existing": replace_existing,
    }
    if misfire_grace_time is not None:
        kwargs["misfire_grace_time"] = max(1, int(misfire_grace_time))
    sched.add_job(
        _guarded(job_id, func, retryable=True),
        DateTrigger(run_date=run_at),
        **kwargs,
    )


def cancel_job(job_id: str) -> None:
    """Remove a scheduled job if present."""
    with _lock:
        sched = _scheduler
    if sched is None or _shutting_down:
        return
    try:
        sched.remove_job(job_id)
    except Exception:
        pass


def state() -> Dict[str, Any]:
    """Lightweight scheduler health for metrics and health checks."""
    with _lock:
        sched = _scheduler
        shutting_down = _shutting_down
    if sched is None:
        return {"running": False, "job_count": 0, "shutting_down": shutting_down}
    try:
        job_count = len(sched.get_jobs())
    except Exception:
        job_count = 0
    return {
        "running": sched.running,
        "job_count": job_count,
        "shutting_down": shutting_down,
        "last_failures": dict(_retry_counts),
    }


def shutdown_background_scheduler() -> None:
    """Stop the shared scheduler (app shutdown)."""
    global _scheduler, _shutting_down
    with _lock:
        _shutting_down = True
        sched = _scheduler
        _scheduler = None
    if sched is not None:
        sched.shutdown(wait=True)
