"""Smoke checks for the shared APScheduler helper."""

import time

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


def test_schedule_in_seconds_sets_misfire_grace():
    """Hour pick was MISSED (grace=1s) while daily occupied the executor for 90s."""
    _reset_scheduler_state()
    job_scheduler.schedule_in_seconds("test-grace-job", lambda: None, 60)
    sched = job_scheduler.get_background_scheduler()
    job = sched.get_job("test-grace-job")
    assert job is not None
    assert job.misfire_grace_time == 180
    job_scheduler.cancel_job("test-grace-job")
    _reset_scheduler_state()
