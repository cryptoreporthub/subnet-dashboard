"""Tests for heavy background job mutex on single Fly VM."""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import internal.heavy_job_gate as gate
from internal.heavy_job_gate import current_holder, heavy_job_slot

_REJECT_HOLDER_RE = re.compile(r"holder=([^\s]+)")


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


class _ConcurrentTracker:
    """Track peak concurrent slot owners."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: set[str] = set()
        self.max_concurrent: int = 0

    def enter(self, name: str) -> None:
        with self._lock:
            self._active.add(name)
            self.max_concurrent = max(self.max_concurrent, len(self._active))

    def exit(self, name: str) -> None:
        with self._lock:
            self._active.discard(name)


class _SectionLock:
    """Wrap a gate lock; pause chosen worker threads at Nth section entry or exit."""

    def __init__(
        self, real: threading.Lock, *, worker_names: frozenset[str]
    ) -> None:
        self._real = real
        self._worker_names = worker_names
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

    def _run_pause(
        self, hooks: dict[int, tuple[Callable[[], None], ...]], section: int
    ) -> None:
        if threading.current_thread().name not in self._worker_names:
            return
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


class _LegacySlotLock:
    """Wrap legacy `_lock` acquire/release for pause hooks on slot ownership."""

    def __init__(
        self,
        real: threading.Lock,
        *,
        worker_names: frozenset[str],
        tracker: _ConcurrentTracker,
    ) -> None:
        self._real = real
        self._worker_names = worker_names
        self._tracker = tracker
        self._after_acquire: tuple[Callable[[], None], ...] = ()
        self._after_release: tuple[Callable[[], None], ...] = ()

    def pause_after_acquire(self, fn: Callable[[], None]) -> None:
        self._after_acquire = (fn,)

    def pause_after_release(self, fn: Callable[[], None]) -> None:
        self._after_release = (fn,)

    def _run(self, hooks: tuple[Callable[[], None], ...]) -> None:
        if threading.current_thread().name not in self._worker_names:
            return
        for fn in hooks:
            fn()

    def acquire(self, blocking: bool = True) -> bool:
        acquired = self._real.acquire(blocking)
        if acquired and not blocking:
            self._tracker.enter(threading.current_thread().name)
            self._run(self._after_acquire)
        return acquired

    def release(self) -> None:
        self._real.release()
        self._run(self._after_release)
        if threading.current_thread().name in self._tracker._active:
            self._tracker.exit(threading.current_thread().name)


@dataclass
class _GateHarness:
    section: Optional[_SectionLock] = None
    slot: Optional[_LegacySlotLock] = None
    raw_state: Optional[threading.Lock] = None
    tracker: _ConcurrentTracker = field(default_factory=_ConcurrentTracker)


def _split_claim_gate() -> bool:
    """True when claim uses separate check/claim state-lock sections (DCL-style)."""
    text = Path(gate.__file__).read_text()
    return "if reject_holder is not None:" in text and text.count(
        "with _state_lock:"
    ) >= 3


def _install_gate_harness(
    monkeypatch, *, worker_names: frozenset[str]
) -> _GateHarness:
    harness = _GateHarness()

    if hasattr(gate, "_state_lock"):
        raw = gate._state_lock
        if isinstance(raw, _SectionLock):
            raw = raw._real
        harness.raw_state = raw
        harness.section = _SectionLock(raw, worker_names=worker_names)
        monkeypatch.setattr(gate, "_state_lock", harness.section)

    if hasattr(gate, "_holder_lock"):
        raw = gate._holder_lock
        if isinstance(raw, _SectionLock):
            raw = raw._real
        if harness.section is None:
            harness.section = _SectionLock(raw, worker_names=worker_names)
            monkeypatch.setattr(gate, "_holder_lock", harness.section)
        else:
            monkeypatch.setattr(gate, "_holder_lock", harness.section)

    if hasattr(gate, "_lock"):
        raw = gate._lock
        if isinstance(raw, _LegacySlotLock):
            raw = raw._real
        harness.slot = _LegacySlotLock(
            raw, worker_names=worker_names, tracker=harness.tracker
        )
        monkeypatch.setattr(gate, "_lock", harness.slot)

    return harness


def _reject_logs(caplog) -> list[str]:
    return [
        r.message
        for r in caplog.records
        if r.name == "internal.heavy_job_gate" and "reject" in r.message
    ]


def _reject_holders(caplog) -> list[str]:
    holders: list[str] = []
    for message in _reject_logs(caplog):
        match = _REJECT_HOLDER_RE.search(message)
        if match:
            holders.append(match.group(1))
    return holders


def _assert_rejects_name_live_holder(caplog) -> None:
    reject_msgs = _reject_logs(caplog)
    assert reject_msgs, "expected at least one reject log"
    holders = _reject_holders(caplog)
    assert holders, "reject logs must include holder="
    assert all(h not in ("None", "unknown") for h in holders)
    assert all("holder=None" not in m for m in reject_msgs)
    assert all("holder=unknown" not in m for m in reject_msgs)


def _race_workers(
    monkeypatch,
    caplog,
    *,
    worker_names: tuple[str, str],
    rounds: int = 1,
) -> _ConcurrentTracker:
    """Synced two-worker race; winner holds until loser has rejected."""
    caplog.set_level(logging.INFO, logger="internal.heavy_job_gate")
    names = frozenset(worker_names)
    harness = _install_gate_harness(monkeypatch, worker_names=names)
    tracker = harness.tracker
    peak = 0

    for _ in range(rounds):
        caplog.clear()
        harness.tracker = _ConcurrentTracker()
        tracker = harness.tracker
        if harness.slot is not None:
            harness.slot._tracker = tracker

        start_barrier = threading.Barrier(2, timeout=3)
        claim_sync = threading.Barrier(2, timeout=3)
        claim_pause = threading.Event()
        release_claim = threading.Event()
        loser_done = threading.Event()
        results: list[bool] = []
        runs = _ThreadRun()
        use_section_sync = harness.section is not None

        def _pause_claim_point() -> None:
            claim_pause.set()
            if use_section_sync:
                claim_sync.wait(timeout=0.5)
            else:
                loser_done.wait(timeout=0.5)
            release_claim.wait(timeout=0.5)

        if harness.section is not None:
            harness.section._depth.clear()
            harness.section.pause_on_exit(1, _pause_claim_point)
        if harness.slot is not None:
            harness.slot.pause_after_acquire(_pause_claim_point)

        def worker(tag: str) -> None:
            start_barrier.wait(timeout=3)
            with heavy_job_slot(tag) as ok:
                if ok:
                    tracker.enter(tag)
                    loser_done.wait(timeout=2)
                    tracker.exit(tag)
                else:
                    loser_done.set()
                results.append(ok)

        for tag in worker_names:
            runs.start(worker, tag, name=tag)

        assert claim_pause.wait(timeout=1), "no worker paused after first claim section"
        release_claim.set()
        runs.assert_clean()

        assert results.count(True) == 1, f"expected one winner, got {results!r}"
        assert results.count(False) == 1, f"expected one loser, got {results!r}"
        assert tracker.max_concurrent == 1, (
            f"overlapping slot owners observed (max={tracker.max_concurrent})"
        )
        _assert_rejects_name_live_holder(caplog)
        peak = max(peak, tracker.max_concurrent)

    tracker.max_concurrent = peak
    return tracker


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
    """Bug (b2/b3): holder cleared before slot free must not make reject log holder=None."""
    caplog.set_level(logging.INFO, logger="internal.heavy_job_gate")
    harness = _install_gate_harness(
        monkeypatch, worker_names=frozenset({"holder", "waiter_pre", "waiter_post"})
    )
    pre_release = threading.Event()
    post_holder_clear = threading.Event()
    release_pre = threading.Event()
    release_post = threading.Event()
    pre_done = threading.Event()
    post_done = threading.Event()
    runs = _ThreadRun()

    def _pause_pre_release() -> None:
        if threading.current_thread().name != "holder":
            return
        pre_release.set()
        release_pre.wait(timeout=0.5)

    def _pause_post_holder_clear() -> None:
        if threading.current_thread().name != "holder":
            return
        post_holder_clear.set()
        release_post.wait(timeout=0.5)

    if harness.section is not None:
        release_section = 3 if _split_claim_gate() else 2
        harness.section.pause_on_enter(release_section, _pause_pre_release)
        harness.section.pause_on_exit(release_section, _pause_post_holder_clear)
    else:
        assert harness.slot is not None
        harness.slot.pause_after_acquire(_pause_pre_release)
        harness.slot.pause_after_release(_pause_post_holder_clear)

    def holder() -> None:
        with heavy_job_slot("holder"):
            pass

    def waiter_pre() -> None:
        pre_release.wait(timeout=1)
        with heavy_job_slot("waiter") as ok:
            assert ok is False
        pre_done.set()
        release_pre.set()

    def waiter_post() -> None:
        post_holder_clear.wait(timeout=1)
        with heavy_job_slot("waiter") as ok:
            if current_holder() == "holder":
                assert ok is False, "must reject while holder name is still set"
            elif ok:
                post_done.set()
                release_post.set()
                return
        post_done.set()
        release_post.set()

    runs.start(holder, name="holder")
    runs.start(waiter_pre, name="waiter_pre")
    runs.start(waiter_post, name="waiter_post")
    assert pre_done.wait(timeout=1), "pre-release waiter never rejected"
    assert post_done.wait(timeout=1), "post-holder-clear waiter never finished"
    runs.assert_clean()
    _assert_rejects_name_live_holder(caplog)
    assert any("holder=holder" in m for m in _reject_logs(caplog))


def test_reject_snapshots_holder_not_live_read(monkeypatch, caplog):
    """Bug (b4): reject must log snapshotted holder, not an unlocked re-read."""
    caplog.set_level(logging.INFO, logger="internal.heavy_job_gate")
    harness = _install_gate_harness(
        monkeypatch, worker_names=frozenset({"holder", "rejecter"})
    )
    reject_checked = threading.Event()
    release_reject = threading.Event()
    holder_may_exit = threading.Event()
    holder_released = threading.Event()
    reject_done = threading.Event()
    runs = _ThreadRun()

    def _pause_after_reject_check() -> None:
        if threading.current_thread().name != "rejecter":
            return
        reject_checked.set()
        release_reject.wait(timeout=1)

    use_section_b4 = harness.section is not None
    if use_section_b4:
        harness.section.pause_on_exit(1, _pause_after_reject_check)
    else:
        assert harness.slot is not None
        harness.slot.pause_after_acquire(_pause_after_reject_check)

    def holder() -> None:
        with heavy_job_slot("holder"):
            if use_section_b4:
                holder_may_exit.wait(timeout=1)
        holder_released.set()

    def rejecter() -> None:
        with heavy_job_slot("waiter") as ok:
            assert ok is False
        reject_done.set()

    runs.start(holder, name="holder")
    time.sleep(0.05)
    runs.start(rejecter, name="rejecter")
    assert reject_checked.wait(timeout=1), "forced pause point never reached"
    if use_section_b4:
        holder_may_exit.set()
        assert holder_released.wait(timeout=1), "holder never released during reject pause"
    release_reject.set()
    assert reject_done.wait(timeout=1), "rejecter never finished"
    if not use_section_b4:
        assert holder_released.wait(timeout=1), "holder never finished"
    runs.assert_clean()
    _assert_rejects_name_live_holder(caplog)
    assert any("holder=holder" in m for m in _reject_logs(caplog))


def test_reject_never_unknown_while_slot_held_forced_timing(monkeypatch, caplog):
    """Bug (c1/c2): acquire gap must not let reject see empty holder while slot is busy."""
    caplog.set_level(logging.INFO, logger="internal.heavy_job_gate")
    harness = _install_gate_harness(
        monkeypatch, worker_names=frozenset({"holder", "waiter"})
    )
    winner_claimed = threading.Event()
    release_winner = threading.Event()
    waiter_done = threading.Event()
    runs = _ThreadRun()

    def _pause_after_claim() -> None:
        if threading.current_thread().name != "holder":
            return
        winner_claimed.set()
        release_winner.wait(timeout=0.5)

    if harness.section is not None:
        claim_section = 2 if _split_claim_gate() else 1
        harness.section.pause_on_exit(claim_section, _pause_after_claim)
    else:
        assert harness.slot is not None
        harness.slot.pause_after_acquire(_pause_after_claim)

    def waiter() -> None:
        winner_claimed.wait(timeout=1)
        with heavy_job_slot("waiter") as ok:
            assert ok is False
        waiter_done.set()

    def holder() -> None:
        with heavy_job_slot("holder"):
            pass

    runs.start(holder, name="holder")
    runs.start(waiter, name="waiter")
    assert waiter_done.wait(timeout=1), "waiter never rejected during post-claim pause"
    release_winner.set()
    runs.assert_clean()
    _assert_rejects_name_live_holder(caplog)
    assert any("holder=holder" in m for m in _reject_logs(caplog))


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
    """Bug (a1/a2): split check/claim must not overlap owners or reject without named holder."""
    tracker = _race_workers(
        monkeypatch, caplog, worker_names=("job_a", "job_b"), rounds=1
    )
    assert tracker.max_concurrent == 1


def test_stress_no_held_with_none_holder(monkeypatch, caplog):
    """Bug (a1/a2): synced claim pairs must not overlap owners or reject without named holder."""
    tracker = _race_workers(
        monkeypatch, caplog, worker_names=("job_x", "job_y"), rounds=10
    )
    assert tracker.max_concurrent == 1
