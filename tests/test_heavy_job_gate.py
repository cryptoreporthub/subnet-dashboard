"""Tests for heavy background job mutex on single Fly VM."""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator, Optional

import internal.heavy_job_gate as gate
from internal.heavy_job_gate import current_holder, heavy_job_slot


class _ThreadRun:
    """Run thread targets and collect uncaught exceptions."""

    def __init__(self) -> None:
        self.errors: list[BaseException] = []
        self._threads: list[threading.Thread] = []

    def start(
        self, target: Callable[..., None], *args: object, name: str
    ) -> threading.Thread:
        def _wrapper() -> None:
            try:
                target(*args)
            except BaseException as exc:  # pragma: no cover - surfaced via assert
                self.errors.append(exc)

        thread = threading.Thread(target=_wrapper, name=name, daemon=True)
        thread.start()
        self._threads.append(thread)
        return thread

    def join_all(self, timeout: float = 3.0) -> None:
        for thread in self._threads:
            thread.join(timeout=timeout)

    def assert_clean(self) -> None:
        self.join_all()
        assert not self.errors, f"worker thread exceptions: {self.errors!r}"


class _SectionLock:
    """Wrap a gate lock; pause chosen threads at Nth section entry or exit."""

    def __init__(self, real: threading.Lock) -> None:
        self._real = real
        self._depth: dict[int, int] = {}
        self._exit_pauses: dict[int, tuple[Callable[[], None], ...]] = {}
        self._enter_pauses: dict[int, tuple[Callable[[], None], ...]] = {}

    def pause_on_exit(self, section: int, fn: Callable[[], None]) -> None:
        self._exit_pauses[section] = (fn,)

    def pause_on_enter(self, section: int, fn: Callable[[], None]) -> None:
        self._enter_pauses[section] = (fn,)

    def _section(self) -> int:
        tid = threading.get_ident()
        self._depth[tid] = self._depth.get(tid, 0) + 1
        return self._depth[tid]

    def _run_pause(self, hooks: dict[int, tuple[Callable[[], None], ...]], section: int) -> None:
        for fn in hooks.get(section, ()):
            fn()

    def __enter__(self) -> _SectionLock:
        section = self._section()
        self._run_pause(self._enter_pauses, section)
        self._real.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        section = self._depth.get(threading.get_ident(), 0)
        self._real.release()
        self._run_pause(self._exit_pauses, section)


def _gate_lock_attr() -> str:
    if hasattr(gate, "_state_lock"):
        return "_state_lock"
    if hasattr(gate, "_holder_lock"):
        return "_holder_lock"
    raise AttributeError("heavy_job_gate has no known state lock")


def _install_section_lock(monkeypatch) -> _SectionLock:
    attr = _gate_lock_attr()
    real = getattr(gate, attr)
    wrapper = _SectionLock(real)
    monkeypatch.setattr(gate, attr, wrapper)
    return wrapper


def _reject_logs(caplog) -> list[str]:
    return [
        r.message
        for r in caplog.records
        if r.name == "internal.heavy_job_gate" and "reject" in r.message
    ]


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
    """Bug (b2): holder cleared before slot free must not make reject log holder=None."""
    caplog.set_level(logging.INFO, logger="internal.heavy_job_gate")
    section_lock = _install_section_lock(monkeypatch)
    pre_release = threading.Event()
    post_holder_clear = threading.Event()
    release_pre = threading.Event()
    release_post = threading.Event()
    pre_done = threading.Event()
    post_done = threading.Event()
    runs = _ThreadRun()

    def _pause_pre_release() -> None:
        if threading.current_thread().name == "holder":
            pre_release.set()
            release_pre.wait(timeout=2)

    def _pause_post_holder_clear() -> None:
        if threading.current_thread().name == "holder":
            post_holder_clear.set()
            release_post.wait(timeout=2)

    section_lock.pause_on_enter(2, _pause_pre_release)
    section_lock.pause_on_exit(2, _pause_post_holder_clear)

    def holder() -> None:
        with heavy_job_slot("holder"):
            pass

    def waiter_pre() -> None:
        pre_release.wait(timeout=2)
        with heavy_job_slot("waiter") as ok:
            assert ok is False
        pre_done.set()
        release_pre.set()

    def waiter_post() -> None:
        post_holder_clear.wait(timeout=2)
        with heavy_job_slot("waiter") as ok:
            if ok:
                post_done.set()
                release_post.set()
                return
        post_done.set()
        release_post.set()

    runs.start(holder, name="holder")
    runs.start(waiter_pre, name="waiter_pre")
    runs.start(waiter_post, name="waiter_post")
    assert pre_done.wait(timeout=2), "pre-release waiter never rejected"
    assert post_done.wait(timeout=2), "post-holder-clear waiter never finished"
    runs.assert_clean()

    reject_msgs = _reject_logs(caplog)
    assert reject_msgs
    assert all("holder=None" not in m for m in reject_msgs)
    assert any("holder=holder" in m for m in reject_msgs)
    assert all("holder=unknown" not in m for m in reject_msgs)


def test_reject_never_unknown_while_slot_held_forced_timing(monkeypatch, caplog):
    """Bug (c2): acquire gap must not let reject see empty holder while slot is busy."""
    caplog.set_level(logging.INFO, logger="internal.heavy_job_gate")
    section_lock = _install_section_lock(monkeypatch)
    winner_claimed = threading.Event()
    release_winner = threading.Event()
    waiter_done = threading.Event()
    runs = _ThreadRun()

    def _pause_after_claim() -> None:
        if threading.current_thread().name == "holder":
            winner_claimed.set()
            release_winner.wait(timeout=2)

    section_lock.pause_on_exit(1, _pause_after_claim)

    def waiter() -> None:
        winner_claimed.wait(timeout=2)
        with heavy_job_slot("waiter") as ok:
            assert ok is False
        waiter_done.set()

    def holder() -> None:
        with heavy_job_slot("holder"):
            pass

    runs.start(holder, name="holder")
    runs.start(waiter, name="waiter")
    assert waiter_done.wait(timeout=2), "waiter never rejected during post-claim pause"
    release_winner.set()
    runs.assert_clean()

    reject_msgs = _reject_logs(caplog)
    assert reject_msgs
    assert all("holder=None" not in m for m in reject_msgs)
    assert all("holder=unknown" not in m for m in reject_msgs)
    assert any("holder=holder" in m for m in reject_msgs)


def test_reject_skip_path_does_not_hold_holder_lock():
    """Reject must not hold gate lock across yield; skip path must stay non-blocking."""
    reject_in_skip = threading.Event()
    release_holder = threading.Event()
    probe: dict[str, object] = {}
    runs = _ThreadRun()

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

    runs.start(holder, name="holder")
    time.sleep(0.05)
    runs.start(rejector, name="rejector")
    time.sleep(0.05)
    runs.start(probe_gate, name="probe")
    time.sleep(0.2)
    release_holder.set()
    runs.assert_clean()

    assert probe["holder"] == "holder"
    assert probe["second_ok"] is False
    assert probe["elapsed"] < 0.2


def test_racing_claim_winner_holder_never_none(monkeypatch, caplog):
    """Bug (a1): split check/claim must not double-win or reject without named holder."""
    caplog.set_level(logging.INFO, logger="internal.heavy_job_gate")
    section_lock = _install_section_lock(monkeypatch)
    barrier = threading.Barrier(2, timeout=3)
    claim_pause = threading.Event()
    release_claim = threading.Event()
    results: list[bool] = []
    unnamed_rejects: list[bool] = []
    runs = _ThreadRun()

    def _pause_first_claim_exit() -> None:
        claim_pause.set()
        release_claim.wait(timeout=2)

    section_lock.pause_on_exit(1, _pause_first_claim_exit)

    def worker(tag: str) -> None:
        barrier.wait(timeout=3)
        with heavy_job_slot(tag) as ok:
            results.append(ok)

    runs.start(worker, "job_a", name="job_a")
    runs.start(worker, "job_b", name="job_b")
    assert claim_pause.wait(timeout=2), "no thread paused after first claim section"
    if current_holder() is None:
        unnamed_rejects.append(True)
    release_claim.set()
    runs.assert_clean()

    reject_msgs = _reject_logs(caplog)
    assert results.count(True) == 1
    assert results.count(False) == 1
    assert unnamed_rejects == []
    assert all("holder=None" not in m for m in reject_msgs)


def test_stress_no_held_with_none_holder(monkeypatch, caplog):
    """Bug (a1): synced claim pairs must never double-win or reject without named holder."""
    caplog.set_level(logging.INFO, logger="internal.heavy_job_gate")
    attr = _gate_lock_attr()
    raw = getattr(gate, attr)
    if isinstance(raw, _SectionLock):
        raw = raw._real
    double_wins = 0
    unnamed_rejects = 0

    for _ in range(10):
        caplog.clear()
        section_lock = _SectionLock(raw)
        monkeypatch.setattr(gate, attr, section_lock)
        barrier = threading.Barrier(2, timeout=3)
        claim_pause = threading.Event()
        release_claim = threading.Event()
        results: list[bool] = []
        round_unnamed: list[bool] = []
        runs = _ThreadRun()
        section_lock._depth.clear()

        def _pause_first_claim_exit() -> None:
            claim_pause.set()
            release_claim.wait(timeout=2)

        section_lock.pause_on_exit(1, _pause_first_claim_exit)

        def _worker(tag: str) -> None:
            barrier.wait(timeout=3)
            with heavy_job_slot(tag) as ok:
                results.append(ok)

        runs.start(_worker, "job_x", name="job_x")
        runs.start(_worker, "job_y", name="job_y")
        assert claim_pause.wait(timeout=2), "no thread paused after first claim section"
        if current_holder() is None:
            round_unnamed.append(True)
        release_claim.set()
        runs.assert_clean()

        if len(results) == 2 and results.count(True) != 1:
            double_wins += 1
        if round_unnamed:
            unnamed_rejects += 1
        reject_msgs = _reject_logs(caplog)
        if any("holder=None" in m for m in reject_msgs):
            unnamed_rejects += 1

    assert double_wins == 0
    assert unnamed_rejects == 0
