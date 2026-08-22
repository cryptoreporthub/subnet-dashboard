"""Smoke checks for the shared APScheduler helper."""

import time
from datetime import datetime, timedelta, timezone

from apscheduler.triggers.date import DateTrigger

from internal import job_scheduler


def _reset_scheduler_state() -> None:
    with job_scheduler._lock:
        sched = job_scheduler._scheduler
        job_scheduler._scheduler = None
        job_scheduler._shutting_down = False
    if sched is not None:
        sched.shutdown(wait=False)


def test_schedule_in_seconds_runs_callback():
    _reset_scheduler_state()
    seen: list[str] = []

    def _tick() -> None:
        seen.append("ok")

    job_scheduler.schedule_in_seconds("test-once-job", _tick, 0.05)
    time.sleep(0.15)
    assert seen == ["ok"]
    job_scheduler.cancel_job("test-once-job")
    _reset_scheduler_state()


def test_late_date_trigger_default_grace_drops_job():
    """APScheduler default misfire_grace_time=1 drops a 2.6s-late one-shot."""
    _reset_scheduler_state()
    seen: list[str] = []

    def _tick() -> None:
        seen.append("ok")

    sched = job_scheduler.get_background_scheduler()
    run_at = datetime.now(timezone.utc) - timedelta(seconds=2.6)
    sched.add_job(
        _tick,
        DateTrigger(run_date=run_at),
        id="late-default",
        replace_existing=True,
        misfire_grace_time=1,
    )
    time.sleep(0.4)
    assert seen == []
    _reset_scheduler_state()


def test_late_date_trigger_60s_grace_still_runs():
    """60s grace (daily-pick retry) still fires when the trigger is ~2.6s late."""
    _reset_scheduler_state()
    seen: list[str] = []

    def _tick() -> None:
        seen.append("ok")

    job_scheduler.schedule_in_seconds(
        "late-grace-job",
        _tick,
        0.05,
        misfire_grace_time=60,
    )
    # Force a late fire: replace with a past DateTrigger using the same grace.
    sched = job_scheduler.get_background_scheduler()
    run_at = datetime.now(timezone.utc) - timedelta(seconds=2.6)
    sched.add_job(
        _tick,
        DateTrigger(run_date=run_at),
        id="late-grace-job",
        replace_existing=True,
        misfire_grace_time=60,
    )
    deadline = time.monotonic() + 2.0
    while not seen and time.monotonic() < deadline:
        time.sleep(0.05)
    assert seen == ["ok"]
    job_scheduler.cancel_job("late-grace-job")
    _reset_scheduler_state()
