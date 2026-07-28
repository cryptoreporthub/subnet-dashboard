"""Tests for heavy background job mutex on single Fly VM."""

from __future__ import annotations

import threading
import time

from internal.heavy_job_gate import current_holder, heavy_job_slot


def test_heavy_job_slot_exclusive():
    with heavy_job_slot("job_a") as a:
        assert a is True
        assert current_holder() == "job_a"
        with heavy_job_slot("job_b") as b:
            assert b is False
    assert current_holder() is None


def test_heavy_job_slot_released_after_exit():
    with heavy_job_slot("job_a"):
        pass
    with heavy_job_slot("job_b") as ok:
        assert ok is True


def test_heavy_job_slot_blocks_second_thread():
    started = threading.Event()
    results: list[bool] = []

    def holder() -> None:
        with heavy_job_slot("holder") as ok:
            results.append(ok)
            started.set()
            time.sleep(0.2)

    def waiter() -> None:
        started.wait(timeout=2)
        with heavy_job_slot("waiter") as ok:
            results.append(ok)

    t1 = threading.Thread(target=holder)
    t2 = threading.Thread(target=waiter)
    t1.start()
    t2.start()
    t1.join(timeout=3)
    t2.join(timeout=3)
    assert results[0] is True
    assert False in results[1:]
