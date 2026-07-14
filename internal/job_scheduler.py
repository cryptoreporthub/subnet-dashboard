"""Shared APScheduler BackgroundScheduler for Fly single-worker background jobs."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

_scheduler: Optional[BackgroundScheduler] = None
_lock = threading.Lock()


def get_background_scheduler() -> BackgroundScheduler:
    """Return the process-wide background scheduler, starting it on first use."""
    global _scheduler
    with _lock:
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
) -> None:
    """Run ``func`` on a fixed interval."""
    sched = get_background_scheduler()
    sched.add_job(
        func,
        IntervalTrigger(seconds=seconds),
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
    try:
        get_background_scheduler().remove_job(job_id)
    except Exception:
        pass


def shutdown_background_scheduler() -> None:
    """Stop the shared scheduler (app shutdown)."""
    global _scheduler
    with _lock:
        if _scheduler is not None:
            _scheduler.shutdown(wait=False)
            _scheduler = None
