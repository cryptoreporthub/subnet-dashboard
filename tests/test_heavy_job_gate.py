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


def test_reject_never_logs_holder_none_on_slow_release(caplog):
    caplog.set_level(logging.INFO, logger="internal.heavy_job_gate")
    holder_ready = threading.Event()
    release_holder = threading.Event()

    def holder() -> None:
        with heavy_job_slot("holder"):
            holder_ready.set()
            release_holder.wait(timeout=2)

    def waiter() -> None:
        holder_ready.wait(timeout=2)
        with heavy_job_slot("waiter") as ok:
            assert ok is False

    t1 = threading.Thread(target=holder)
    t2 = threading.Thread(target=waiter)
    t1.start()
    t2.start()
    time.sleep(0.05)
    release_holder.set()
    t1.join(timeout=3)
    t2.join(timeout=3)

    reject_msgs = [
        r.message
        for r in caplog.records
        if r.name == "internal.heavy_job_gate" and "reject" in r.message
    ]
    assert reject_msgs
    assert all("holder=None" not in m for m in reject_msgs)
    assert any("holder=holder" in m for m in reject_msgs)
    assert all("holder=unknown" not in m for m in reject_msgs)


def test_reject_never_unknown_while_slot_held_forced_timing(caplog):
    """Forced-timing repro: holder is never None/unknown while the slot is held."""
    caplog.set_level(logging.INFO, logger="internal.heavy_job_gate")
    holder_ready = threading.Event()
    release_holder = threading.Event()

    def waiter() -> None:
        holder_ready.wait(timeout=2)
        with heavy_job_slot("waiter") as ok:
            assert ok is False

    def holder() -> None:
        with heavy_job_slot("holder"):
            holder_ready.set()
            release_holder.wait(timeout=2)

    t1 = threading.Thread(target=holder)
    t2 = threading.Thread(target=waiter)
    t1.start()
    t2.start()
    time.sleep(0.05)
    release_holder.set()
    t2.join(timeout=3)
    t1.join(timeout=3)
    reject_msgs = [
        r.message
        for r in caplog.records
        if r.name == "internal.heavy_job_gate" and "reject" in r.message
    ]
    assert reject_msgs
    assert all("holder=None" not in m for m in reject_msgs)
    assert all("holder=unknown" not in m for m in reject_msgs)
    assert any("holder=holder" in m for m in reject_msgs)


def test_reject_skip_path_does_not_hold_holder_lock():
    """Reject must not hold _state_lock across yield; skip path must stay non-blocking."""
    reject_in_skip = threading.Event()
    release_holder = threading.Event()
    probe: dict[str, object] = {}

    def holder() -> None:
        with heavy_job_slot("holder"):
            release_holder.wait(timeout=3)

    def rejector() -> None:
        with heavy_job_slot("waiter") as ok:
            assert ok is False
            reject_in_skip.set()
            time.sleep(1.0)

    def probe_gate() -> None:
        reject_in_skip.wait(timeout=2)
        started = time.perf_counter()
        probe["holder"] = current_holder()
        with heavy_job_slot("probe") as ok:
            probe["second_ok"] = ok
        probe["elapsed"] = time.perf_counter() - started

    t_holder = threading.Thread(target=holder)
    t_reject = threading.Thread(target=rejector)
    t_probe = threading.Thread(target=probe_gate)
    t_holder.start()
    time.sleep(0.05)
    t_reject.start()
    time.sleep(0.05)
    t_probe.start()
    time.sleep(0.2)
    release_holder.set()
    t_holder.join(timeout=3)
    t_reject.join(timeout=3)
    t_probe.join(timeout=3)

    assert probe["holder"] == "holder"
    assert probe["second_ok"] is False
    assert probe["elapsed"] < 0.2


def test_racing_claim_winner_holder_never_none(monkeypatch):
    """Two callers race at claim; winner must keep holder set for entire hold."""
    from contextlib import contextmanager

    barrier = threading.Barrier(2, timeout=3)
    real_slot = gate.heavy_job_slot
    results: list[bool] = []
    holder_none_while_held: list[str] = []

    @contextmanager
    def _synced_slot(name: str):
        barrier.wait(timeout=3)
        with real_slot(name) as ok:
            if ok:
                for _ in range(20):
                    if current_holder() is None:
                        holder_none_while_held.append(name)
                    time.sleep(0.001)
            yield ok

    monkeypatch.setattr(gate, "heavy_job_slot", _synced_slot)

    def worker(tag: str) -> None:
        with _synced_slot(tag) as ok:
            results.append(ok)

    t1 = threading.Thread(target=worker, args=("job_a",))
    t2 = threading.Thread(target=worker, args=("job_b",))
    t1.start()
    t2.start()
    t1.join(timeout=3)
    t2.join(timeout=3)

    assert results.count(True) == 1
    assert results.count(False) == 1
    assert holder_none_while_held == []


def test_stress_no_held_with_none_holder():
    """Short stress: zero windows where slot is held but holder is None."""
    held_with_none = 0
    count_lock = threading.Lock()

    def worker(tag: int) -> None:
        nonlocal held_with_none
        with heavy_job_slot(f"job_{tag}") as ok:
            if not ok:
                return
            if current_holder() is None:
                with count_lock:
                    held_with_none += 1

    for batch in range(50):
        threads = [
            threading.Thread(target=worker, args=(batch * 20 + i,))
            for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

    assert held_with_none == 0
