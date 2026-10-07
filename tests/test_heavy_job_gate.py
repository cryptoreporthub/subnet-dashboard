"""Tests for heavy background job mutex on single Fly VM."""

from __future__ import annotations

import logging
import threading
import time

import internal.heavy_job_gate as gate
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


def test_heavy_job_slot_survives_acquire_log_exception(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("acquire log failed")

    monkeypatch.setattr(gate.logger, "info", _boom)
    with heavy_job_slot("job_a") as ok:
        assert ok is True
        assert current_holder() == "job_a"
    assert current_holder() is None
    with heavy_job_slot("job_b") as ok:
        assert ok is True


def test_heavy_job_slot_survives_release_log_exception(monkeypatch):
    real_info = gate.logger.info
    calls = {"n": 0}

    def _fail_release_only(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1 or (
            args and isinstance(args[0], str) and "release" in args[0]
        ):
            raise RuntimeError("release log failed")
        return real_info(*args, **kwargs)

    monkeypatch.setattr(gate.logger, "info", _fail_release_only)
    with heavy_job_slot("job_a") as ok:
        assert ok is True
    assert current_holder() is None
    with heavy_job_slot("job_b") as ok:
        assert ok is True


def test_reject_never_logs_holder_none_on_slow_release(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="internal.heavy_job_gate")
    releasing = threading.Event()
    release_done = threading.Event()

    class _SlowGateLock:
        def __init__(self) -> None:
            self._inner = threading.Lock()

        def acquire(self, blocking: bool = True) -> bool:
            return self._inner.acquire(blocking)

        def release(self) -> None:
            releasing.set()
            time.sleep(0.1)
            self._inner.release()
            release_done.set()

    monkeypatch.setattr(gate, "_lock", _SlowGateLock())

    def holder() -> None:
        with heavy_job_slot("holder"):
            pass

    def waiter() -> None:
        releasing.wait(timeout=2)
        with heavy_job_slot("waiter") as ok:
            assert ok is False

    t1 = threading.Thread(target=holder)
    t2 = threading.Thread(target=waiter)
    t1.start()
    t2.start()
    t1.join(timeout=3)
    t2.join(timeout=3)
    release_done.wait(timeout=2)

    reject_msgs = [
        r.message
        for r in caplog.records
        if r.name == "internal.heavy_job_gate" and "reject" in r.message
    ]
    assert reject_msgs
    assert all("holder=None" not in m for m in reject_msgs)
    assert any("holder=holder" in m for m in reject_msgs)
