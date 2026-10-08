"""Tests for heavy background job mutex on single Fly VM."""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import pytest

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

    def holds(self, name: str) -> bool:
        with self._lock:
            return name in self._active


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
        self._before_acquire: tuple[Callable[[], None], ...] = ()
        self._after_acquire: tuple[Callable[[], None], ...] = ()
        self._before_release: tuple[Callable[[], None], ...] = ()
        self._after_release: tuple[Callable[[], None], ...] = ()

    def pause_before_acquire(self, fn: Callable[[], None]) -> None:
        self._before_acquire = (fn,)

    def pause_after_acquire(self, fn: Callable[[], None]) -> None:
        self._after_acquire = (fn,)

    def pause_before_release(self, fn: Callable[[], None]) -> None:
        self._before_release = (fn,)

    def pause_after_release(self, fn: Callable[[], None]) -> None:
        self._after_release = (fn,)

    def _run(self, hooks: tuple[Callable[[], None], ...]) -> None:
        if threading.current_thread().name not in self._worker_names:
            return
        for fn in hooks:
            fn()

    def acquire(self, blocking: bool = True) -> bool:
        self._run(self._before_acquire)
        acquired = self._real.acquire(blocking)
        if acquired and not blocking:
            self._tracker.enter(threading.current_thread().name)
            self._run(self._after_acquire)
        return acquired

    def release(self) -> None:
        self._run(self._before_release)
        self._real.release()
        self._run(self._after_release)
        name = threading.current_thread().name
        if self._tracker.holds(name):
            self._tracker.exit(name)


@dataclass
class _GateHarness:
    section: Optional[_SectionLock] = None
    slot: Optional[_LegacySlotLock] = None
    raw_state: Optional[threading.Lock] = None
    tracker: _ConcurrentTracker = field(default_factory=_ConcurrentTracker)

    def reset_tracker(self) -> _ConcurrentTracker:
        self.tracker = _ConcurrentTracker()
        if self.slot is not None:
            self.slot._tracker = self.tracker
        return self.tracker


def _gate_holder() -> Optional[str]:
    """Read holder name without re-entering wrapped test locks."""
    if not hasattr(gate, "_holder"):
        raise AttributeError("gate internals not recognised: missing _holder")
    return gate._holder


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


def _arm_claim_exit_pause(
    harness: _GateHarness,
    *,
    holder_name: str,
    pause_fn: Callable[[], None],
) -> None:
    """Pause at first section exit where this thread owns the named holder."""

    fired = threading.Event()

    def _on_claim_exit() -> None:
        if threading.current_thread().name != holder_name:
            return
        if fired.is_set():
            return
        if _gate_holder() != holder_name:
            return
        fired.set()
        pause_fn()

    if harness.section is not None:
        for section in range(1, 6):
            harness.section.pause_on_exit(section, _on_claim_exit)
    elif harness.slot is not None:
        # Legacy gates set _holder after acquire; pause on slot ownership.
        def _on_slot_acquire() -> None:
            if threading.current_thread().name != holder_name:
                return
            if fired.is_set():
                return
            fired.set()
            pause_fn()

        harness.slot.pause_after_acquire(_on_slot_acquire)


def _arm_release_enter_pause(
    harness: _GateHarness,
    *,
    holder_name: str,
    body_done: threading.Event,
    pause_fn: Callable[[], None],
) -> None:
    """Pause at first section enter after the holder body finished."""

    fired = threading.Event()

    def _on_release_enter() -> None:
        if threading.current_thread().name != holder_name:
            return
        if fired.is_set() or not body_done.is_set():
            return
        fired.set()
        pause_fn()

    if harness.section is not None:
        for section in range(1, 6):
            harness.section.pause_on_enter(section, _on_release_enter)
    elif harness.slot is not None:
        harness.slot.pause_before_release(pause_fn)


def _arm_release_exit_pause(
    harness: _GateHarness,
    *,
    holder_name: str,
    body_done: threading.Event,
    pause_fn: Callable[[], None],
) -> None:
    """Pause at first section exit after the holder body finished."""

    fired = threading.Event()

    def _on_release_exit() -> None:
        if threading.current_thread().name != holder_name:
            return
        if fired.is_set() or not body_done.is_set():
            return
        fired.set()
        pause_fn()

    if harness.section is not None:
        for section in range(1, 6):
            harness.section.pause_on_exit(section, _on_release_exit)
    elif harness.slot is not None:
        harness.slot.pause_after_release(pause_fn)


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
        tracker = harness.reset_tracker()

        start_barrier = threading.Barrier(2, timeout=3)
        claim_pause = threading.Event()
        release_claim = threading.Event()
        loser_done = threading.Event()
        results: list[bool] = []
        runs = _ThreadRun()

        claim_fired = threading.Event()
        split_holder_slot = (
            harness.section is not None and harness.slot is not None
        )
        precheck_sync = threading.Barrier(2, timeout=3) if split_holder_slot else None
        claim_sync = threading.Barrier(2, timeout=3) if split_holder_slot else None
        lock_sync = threading.Barrier(2, timeout=3) if split_holder_slot else None

        def _sync_precheck_exit() -> None:
            if precheck_sync is not None:
                precheck_sync.wait(timeout=0.5)

        def _sync_claim_exit() -> None:
            if claim_sync is not None:
                claim_sync.wait(timeout=0.5)

        def _sync_lock_acquire() -> None:
            if lock_sync is not None:
                lock_sync.wait(timeout=0.5)

        slot_only = harness.slot is not None and harness.section is None

        def _pause_claim_point() -> None:
            tag = threading.current_thread().name
            if claim_fired.is_set():
                return
            if not slot_only:
                deadline = time.perf_counter() + 0.05
                while _gate_holder() != tag:
                    if time.perf_counter() > deadline:
                        return
                    time.sleep(0)
                if claim_fired.is_set():
                    return
            claim_fired.set()
            claim_pause.set()
            loser_done.wait(timeout=2)
            release_claim.wait(timeout=2)

        # One pause point only: section OR slot, never both.
        if split_holder_slot:
            # 574-style: both pass precheck, both claim, then race on slot lock.
            harness.section._depth.clear()
            harness.section.pause_on_exit(1, _sync_precheck_exit)
            harness.section.pause_on_exit(2, _sync_claim_exit)
            harness.slot.pause_before_acquire(_sync_lock_acquire)
        elif harness.slot is not None:
            harness.slot.pause_after_acquire(_pause_claim_point)
        elif harness.section is not None:
            harness.section._depth.clear()
            for section in range(1, 6):
                harness.section.pause_on_exit(section, _pause_claim_point)

        def worker(tag: str) -> None:
            start_barrier.wait(timeout=3)
            with heavy_job_slot(tag) as ok:
                if ok:
                    tracker.enter(tag)
                    loser_done.wait(timeout=2)
                    assert current_holder() == tag, (
                        f"holder wiped/overwritten while {tag} holds"
                    )
                    tracker.exit(tag)
                else:
                    loser_done.set()
                results.append(ok)

        for tag in worker_names:
            runs.start(worker, tag, name=tag)

        if split_holder_slot:
            runs.join_all()
        else:
            assert claim_pause.wait(timeout=1), (
                "no worker paused after first claim section"
            )
            release_claim.set()
            runs.assert_clean()
        if split_holder_slot:
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
    holder_body_done = threading.Event()
    runs = _ThreadRun()

    def _pause_pre_release() -> None:
        pre_release.set()
        release_pre.wait(timeout=0.5)

    def _pause_post_holder_clear() -> None:
        post_holder_clear.set()
        release_post.wait(timeout=0.5)

    _arm_release_enter_pause(
        harness,
        holder_name="holder",
        body_done=holder_body_done,
        pause_fn=_pause_pre_release,
    )
    _arm_release_exit_pause(
        harness,
        holder_name="holder",
        body_done=holder_body_done,
        pause_fn=_pause_post_holder_clear,
    )

    def holder() -> None:
        with heavy_job_slot("holder"):
            holder_body_done.set()

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


def test_same_name_reacquire_keeps_holder_visible(monkeypatch):
    """Bug (wipe): release must not free the slot and then clear the holder, which
    would wipe the name of a same-name job that re-acquired in between.

    Every lock step `first` takes during release is a checkpoint. At each one,
    `second` tries a same-name re-acquire:
      * slot still held -> it must be rejected and current_holder() must be "resolver";
      * slot already free -> it must succeed, and current_holder() must still be
        "resolver" after `first` finishes releasing.
    On the atomic gate release is one locked step, so only the first case is
    reachable; the test asserts that it was reached instead of passing vacuously.
    """
    harness = _install_gate_harness(
        monkeypatch, worker_names=frozenset({"first", "second"})
    )
    if harness.section is None and harness.slot is None:
        pytest.skip("gate internals not recognised; cannot place release checkpoints")
    body_done = threading.Event()
    first_done = threading.Event()
    at_checkpoint = threading.Semaphore(0)
    resume_first = threading.Semaphore(0)
    reacquired = threading.Event()
    second_gone = threading.Event()
    result: dict[str, object] = {"held_checks": 0, "gap": None, "stuck": False}
    runs = _ThreadRun()

    def _checkpoint() -> None:
        if threading.current_thread().name != "first":
            return
        if not body_done.is_set() or reacquired.is_set() or second_gone.is_set():
            return
        at_checkpoint.release()
        if not resume_first.acquire(timeout=2):
            result["stuck"] = True

    if harness.section is not None:
        for section in range(1, 8):
            harness.section.pause_on_enter(section, _checkpoint)
    if harness.slot is not None:
        harness.slot.pause_before_release(_checkpoint)
        harness.slot.pause_after_release(_checkpoint)

    def first() -> None:
        with heavy_job_slot("resolver") as ok:
            assert ok is True
            body_done.set()
        first_done.set()

    def second() -> None:
        try:
            _second()
        finally:
            second_gone.set()

    def _second() -> None:
        assert body_done.wait(timeout=1), "first never entered its body"
        while True:
            if not at_checkpoint.acquire(timeout=0.01):
                if first_done.is_set():
                    break
                continue
            with heavy_job_slot("resolver") as ok:
                try:
                    if not ok:
                        holder = current_holder()
                        assert holder == "resolver", (
                            f"slot held during release but holder={holder!r}"
                        )
                        result["held_checks"] += 1
                        continue
                    # Slot is free while first still has release work: wipe window.
                    result["gap"] = True
                    assert current_holder() == "resolver"
                    reacquired.set()
                finally:
                    resume_first.release()
                assert first_done.wait(timeout=1), "first never finished release"
                assert current_holder() == "resolver", (
                    "holder wiped while same-name owner holds slot"
                )
            return
        result["gap"] = False
        with heavy_job_slot("resolver") as ok:
            assert ok is True
            assert current_holder() == "resolver"

    runs.start(first, name="first")
    runs.start(second, name="second")
    runs.assert_clean()
    assert not result["stuck"], "first timed out waiting at a release checkpoint"
    assert first_done.is_set(), "first never released"
    assert result["gap"] is not None, "second never finished"
    assert result["held_checks"] >= 1, (
        "no release checkpoint reached while slot held; interleaving not exercised"
    )
    assert current_holder() is None


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
    rejecter_failed = threading.Event()
    reject_done = threading.Event()
    runs = _ThreadRun()

    def _pause_after_reject_check() -> None:
        if threading.current_thread().name != "rejecter":
            return
        if current_holder() in (None, "waiter"):
            return
        reject_checked.set()
        release_reject.wait(timeout=1)

    use_section_b4 = harness.section is not None
    if use_section_b4:
        for section in range(1, 6):
            harness.section.pause_on_exit(section, _pause_after_reject_check)

    holder_in_slot = threading.Event()

    def holder() -> None:
        with heavy_job_slot("holder") as ok:
            assert ok is True
            holder_in_slot.set()
            if use_section_b4:
                holder_may_exit.wait(timeout=1)
            else:
                assert rejecter_failed.wait(timeout=1), (
                    "rejecter finished before failed acquire"
                )
        holder_released.set()

    def rejecter() -> None:
        holder_in_slot.wait(timeout=1)
        with heavy_job_slot("waiter") as ok:
            rejecter_failed.set()
            assert ok is False
        reject_done.set()

    holder_ready = threading.Event()

    def _wait_holder() -> None:
        deadline = time.time() + 1
        while time.time() < deadline:
            if current_holder() == "holder":
                holder_ready.set()
                return
            time.sleep(0.001)

    runs.start(_wait_holder, name="probe")
    runs.start(holder, name="holder")
    assert holder_ready.wait(timeout=1), "holder never acquired slot"
    runs.start(rejecter, name="rejecter")
    if use_section_b4:
        assert reject_checked.wait(timeout=1), "forced pause point never reached"
        holder_may_exit.set()
        assert holder_released.wait(timeout=1), "holder never released during reject pause"
        release_reject.set()
    else:
        assert rejecter_failed.wait(timeout=1), "rejecter never attempted acquire"
        holder_may_exit.set()
        assert holder_released.wait(timeout=1), "holder released before reject logged"
    assert reject_done.wait(timeout=1), "rejecter never finished"
    runs.assert_clean()
    _assert_rejects_name_live_holder(caplog)
    assert any("holder=holder" in m for m in _reject_logs(caplog))


def test_reject_snapshots_holder_before_lock_read(monkeypatch, caplog):
    """Bug (b4 variant): reject must snapshot holder inside the busy check lock."""
    if not hasattr(gate, "_state_lock"):
        return
    caplog.set_level(logging.INFO, logger="internal.heavy_job_gate")
    harness = _install_gate_harness(
        monkeypatch, worker_names=frozenset({"holder", "rejecter"})
    )
    assert harness.section is not None
    rejecter_at_entry = threading.Event()
    holder_may_claim = threading.Event()
    reject_done = threading.Event()
    runs = _ThreadRun()

    def _pause_rejecter_entry() -> None:
        if threading.current_thread().name != "rejecter":
            return
        rejecter_at_entry.set()
        holder_may_claim.wait(timeout=1)

    harness.section.pause_on_enter(1, _pause_rejecter_entry)

    def holder() -> None:
        rejecter_at_entry.wait(timeout=1)
        with heavy_job_slot("holder") as ok:
            assert ok is True
            holder_may_claim.set()
            assert reject_done.wait(timeout=1), "rejecter never finished during hold"

    def rejecter() -> None:
        with heavy_job_slot("waiter") as ok:
            assert ok is False
        reject_done.set()

    runs.start(rejecter, name="rejecter")
    assert rejecter_at_entry.wait(timeout=1), "rejecter never paused at entry"
    runs.start(holder, name="holder")
    assert reject_done.wait(timeout=1), "rejecter never finished"
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

    _arm_claim_exit_pause(
        harness, holder_name="holder", pause_fn=_pause_after_claim
    )

    def waiter() -> None:
        winner_claimed.wait(timeout=1)
        with heavy_job_slot("waiter") as ok:
            assert ok is False
        waiter_done.set()

    def holder() -> None:
        with heavy_job_slot("holder"):
            assert winner_claimed.wait(timeout=1), "claim pause never reached"

    runs.start(holder, name="holder")
    runs.start(waiter, name="waiter")
    assert waiter_done.wait(timeout=1), "waiter never rejected during post-claim pause"
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
