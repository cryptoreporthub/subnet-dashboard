"""Shared APScheduler BackgroundScheduler for Fly single-worker background jobs."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

_scheduler: Optional[BackgroundScheduler] = None
_shutting_down = False
_lock = threading.Lock()


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
        func,
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
) -> None:
    """Run ``func`` once after ``seconds``."""
    if _shutting_down:
        return
    sched = get_background_scheduler()
    run_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    sched.add_job(
        func,
        DateTrigger(run_date=run_at),
        id=job_id,
        replace_existing=replace_existing,
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
    return {"running": sched.running, "job_count": job_count, "shutting_down": shutting_down}


def shutdown_background_scheduler() -> None:
    """Stop the shared scheduler (app shutdown)."""
    global _scheduler, _shutting_down
    with _lock:
        _shutting_down = True
        sched = _scheduler
        _scheduler = None
    if sched is not None:
        sched.shutdown(wait=True)
