"""Smoke checks for the shared APScheduler helper."""

import time

from internal import job_scheduler


def test_schedule_in_seconds_runs_callback():
    seen: list[str] = []

    def _tick() -> None:
        seen.append("ok")

    job_scheduler.schedule_in_seconds("test-once-job", _tick, 0.05)
    time.sleep(0.15)
    assert seen == ["ok"]
    job_scheduler.cancel_job("test-once-job")
    job_scheduler.shutdown_background_scheduler()
