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
