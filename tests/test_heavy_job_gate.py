"""Tests for heavy background job mutex on single Fly VM."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Callable, Optional

import internal.heavy_job_gate as gate
from internal.heavy_job_gate import current_holder, heavy_job_slot


def _install_pause_hook(monkeypatch, fn: Callable[[str], None]) -> None:
    monkeypatch.setattr(gate, "_pause_hook", fn)


def _held_without_holder() -> bool:
    with gate._state_lock:
        return gate._held and gate._holder is None


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
    """Bug (b): holder cleared before slot free must not make reject log holder=None."""
    caplog.set_level(logging.INFO, logger="internal.heavy_job_gate")
    winner_claimed = threading.Event()
    release_winner = threading.Event()
    waiter_done = threading.Event()

    def _hook(phase: str) -> None:
        if phase == "pre_release":
            winner_claimed.set()
            release_winner.wait(timeout=2)

    _install_pause_hook(monkeypatch, _hook)

    def holder() -> None:
        with heavy_job_slot("holder"):
            pass

    def waiter() -> None:
        winner_claimed.wait(timeout=2)
        with heavy_job_slot("waiter") as ok:
            assert ok is False
        waiter_done.set()

    t1 = threading.Thread(target=holder)
    t2 = threading.Thread(target=waiter)
    t1.start()
    t2.start()
    assert waiter_done.wait(timeout=2), "waiter never rejected during pre_release pause"
    release_winner.set()
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


def test_reject_never_unknown_while_slot_held_forced_timing(monkeypatch, caplog):
    """Bug (c): acquire gap must not let reject see empty holder while slot is busy."""
    caplog.set_level(logging.INFO, logger="internal.heavy_job_gate")
    winner_claimed = threading.Event()
    release_winner = threading.Event()
    waiter_done = threading.Event()

    def _hook(phase: str) -> None:
        if phase == "post_claim_acquired":
            winner_claimed.set()
            release_winner.wait(timeout=2)

    _install_pause_hook(monkeypatch, _hook)

    def waiter() -> None:
        winner_claimed.wait(timeout=2)
        with heavy_job_slot("waiter") as ok:
            assert ok is False
        waiter_done.set()

    def holder() -> None:
        with heavy_job_slot("holder"):
            pass

    t1 = threading.Thread(target=holder)
    t2 = threading.Thread(target=waiter)
    t1.start()
    t2.start()
    assert waiter_done.wait(timeout=2), "waiter never rejected during post_claim pause"
    release_winner.set()
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
    """Bug (a): split free-check/claim must not let two winners or holder=None while held."""
    barrier = threading.Barrier(2, timeout=3)
    at_check = threading.Barrier(2, timeout=3)
    release_check = threading.Event()
    winner_claimed = threading.Event()
    release_winner = threading.Event()
    loser_done = threading.Event()
    results: list[bool] = []
    holder_none_while_held: list[str] = []

    def _hook(phase: str) -> None:
        if phase == "between_check_and_claim":
            try:
                at_check.wait(timeout=0.2)
            except threading.BrokenBarrierError:
                return
            release_check.wait(timeout=2)
        elif phase == "post_claim_acquired":
            winner_claimed.set()
            release_winner.wait(timeout=2)

    _install_pause_hook(monkeypatch, _hook)

    def probe() -> None:
        loser_done.wait(timeout=2)
        for _ in range(50):
            if _held_without_holder():
                holder_none_while_held.append("probe")
            time.sleep(0.001)

    def worker(tag: str) -> None:
        barrier.wait(timeout=3)
        with heavy_job_slot(tag) as ok:
            results.append(ok)
            if not ok:
                loser_done.set()

    t1 = threading.Thread(target=worker, args=("job_a",))
    t2 = threading.Thread(target=worker, args=("job_b",))
    t_probe = threading.Thread(target=probe)
    t1.start()
    t2.start()
    t_probe.start()
    time.sleep(0.25)
    release_check.set()
    assert winner_claimed.wait(timeout=2), "winner must pause at post_claim_acquired"
    assert loser_done.wait(timeout=2), "loser never rejected during winner post_claim pause"
    t_probe.join(timeout=3)
    release_winner.set()
    t1.join(timeout=3)
    t2.join(timeout=3)

    assert results.count(True) == 1
    assert results.count(False) == 1
    assert holder_none_while_held == []


def test_stress_no_held_with_none_holder(monkeypatch):
    """Bug (a): concurrent claim pairs must never double-win or leave held with holder=None."""
    violations = 0
    double_wins = 0
    count_lock = threading.Lock()
    round_sync: dict[str, object] = {}

    def _hook(phase: str) -> None:
        if phase == "between_check_and_claim":
            pause = round_sync.get("pause")
            release = round_sync.get("release")
            if not isinstance(pause, threading.Barrier) or not isinstance(
                release, threading.Event
            ):
                return
            try:
                pause.wait(timeout=0.2)
            except threading.BrokenBarrierError:
                return
            release.wait(timeout=2)

    _install_pause_hook(monkeypatch, _hook)

    def _pair_round() -> None:
        nonlocal violations, double_wins
        barrier = threading.Barrier(2, timeout=3)
        results: list[bool] = []
        round_sync["pause"] = threading.Barrier(2, timeout=3)
        round_sync["release"] = threading.Event()

        def _worker(tag: str) -> None:
            nonlocal violations
            barrier.wait(timeout=3)
            with heavy_job_slot(tag) as ok:
                results.append(ok)
                if ok:
                    for _ in range(10):
                        if _held_without_holder():
                            with count_lock:
                                violations += 1
                        time.sleep(0.001)

        t1 = threading.Thread(target=_worker, args=("job_x",))
        t2 = threading.Thread(target=_worker, args=("job_y",))
        t1.start()
        t2.start()
        time.sleep(0.25)
        release = round_sync.get("release")
        if isinstance(release, threading.Event):
            release.set()
        t1.join(timeout=3)
        t2.join(timeout=3)
        if results.count(True) != 1:
            with count_lock:
                double_wins += 1

    for _ in range(30):
        _pair_round()

    assert violations == 0
    assert double_wins == 0
