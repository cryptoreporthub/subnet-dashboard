
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
from apscheduler.events import EVENT_JOB_MISSED

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
# DateTrigger default grace is 1s; a 90s daily-pick tick then MISSES the hour job.
_JOB_MISFIRE_GRACE_SECONDS = int(os.environ.get("JOB_MISFIRE_GRACE_SECONDS", "180"))
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
        sched = _scheduler
    install_missed_event_logger()
    return sched


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
        misfire_grace_time=_JOB_MISFIRE_GRACE_SECONDS,
    )


def schedule_in_seconds(
    job_id: str,
    func: Callable[[], None],
    seconds: float,
    *,
    replace_existing: bool = True,
) -> None:
    """Run ``func`` once after ``seconds``."""
    if _shutting_down:
        return
    sched = get_background_scheduler()
    run_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    sched.add_job(
        _guarded(job_id, func, retryable=True),
        DateTrigger(run_date=run_at),
        id=job_id,
        replace_existing=replace_existing,
        misfire_grace_time=_JOB_MISFIRE_GRACE_SECONDS,
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



def job_inventory() -> Dict[str, Any]:
    """Read-only worker-side job inventory for diagnostics (FP7).

    Returns APScheduler job id/name/next_run_time/misfire_grace_time/pending for
    every registered job plus retry counts. Classification aid for scheduler
    stalls: shows whether each scheduler still holds a live trigger.
    """
    with _lock:
        sched = _scheduler
    if sched is None:
        return {"running": False, "job_count": 0, "jobs": [], "last_failures": {}}
    try:
        jobs = sched.get_jobs()
    except Exception as exc:
        return {"running": False, "job_count": 0, "jobs": [], "error": str(exc)}
    out = []
    for job in jobs:
        try:
            nrt = job.next_run_time.isoformat() if job.next_run_time else None
        except Exception:
            nrt = None
        try:
            trigger = repr(job.trigger)
        except Exception:
            trigger = None
        out.append(
            {
                "id": job.id,
                "name": getattr(job, "name", None),
                "next_run_time": nrt,
                "misfire_grace_time": getattr(job, "misfire_grace_time", None),
                "pending": getattr(job, "pending", None),
                "trigger": trigger,
            }
        )
    return {
        "running": sched.running,
        "job_count": len(out),
        "jobs": out,
        "last_failures": dict(_retry_counts),
    }


_missed_listener_installed = False


def install_missed_event_logger() -> bool:
    """Attach a logging-only EVENT_JOB_MISSED listener (FP7).

    Logs when a scheduled one-shot job is missed/misfired, so re-arm failures
    are visible in worker logs instead of failing silently. Idempotent.
    """
    global _missed_listener_installed
    if _missed_listener_installed:
        return True
    with _lock:
        sched = _scheduler
        if sched is None:
            return False
        sched.add_listener(_on_job_missed, EVENT_JOB_MISSED)
        _missed_listener_installed = True
        return True


def _on_job_missed(event: Any) -> None:
    logger.warning(
        "background job MISSED: %s (job_id=%s, scheduled=%s, misfire_grace_time=%s)",
        getattr(event, "job", None),
        getattr(event, "job_id", "?"),
        getattr(event, "scheduled_run_time", "?"),
        getattr(event, "misfire_grace_time", "?"),
    )
