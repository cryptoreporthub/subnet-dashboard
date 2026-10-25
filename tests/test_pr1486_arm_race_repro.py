"""PR #1486 arm-race repros (scratch, not part of the contract suite).

Case 1b: thread.start() raises after liveness.start() in immediate mode —
lifecycle reads started with no tick armed (documented residual of c6247206).

Case 2: stall-guard revive swaps schedulers between the old producer's
_is_registered() check and its schedule_in_seconds() re-arm; the late re-arm
replaces (replace_existing=True) the new scheduler's pending tick.
"""

from __future__ import annotations

import threading

import pytest

from internal.council import score_snapshots as snaps


@pytest.fixture(autouse=True)
def _reset_score_snapshot_scheduler():
    from internal.job_scheduler import cancel_job
    from internal.store.soul_map_io import _cache as soul_map_cache

    snaps.stop_score_snapshot_scheduler()
    with snaps._lock:
        snaps._TICK_ACTIVE = False
        snaps._write_future = None
    soul_map_cache.clear()
    cancel_job(snaps.JOB_ID)
    yield
    snaps.stop_score_snapshot_scheduler()
    soul_map_cache.clear()
    cancel_job(snaps.JOB_ID)


def _soul(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    return soul


def test_thread_start_failure_after_liveness_start_reports_running_with_no_tick(
    tmp_path, monkeypatch
):
    """Case 1b residual at 27f6b391: in immediate mode liveness.start() now
    runs BEFORE the tick thread (c6247206), but if thread.start() itself
    raises, the lifecycle stays started with nothing armed and no primitive
    stops/resets it."""
    _soul(tmp_path, monkeypatch)
    monkeypatch.setattr(
        snaps, "SCORE_SNAPSHOTS_PATH", str(tmp_path / "score_snapshots.json")
    )
    monkeypatch.setattr(snaps, "schedule_in_seconds", lambda *a, **k: None)
    ticks: list = []
    monkeypatch.setattr(
        snaps.ScoreSnapshotScheduler,
        "_tick",
        lambda self, reschedule=True: ticks.append(1) or {"ok": False, "skipped": "test"},
    )
    real_thread_start = threading.Thread.start

    def raising_start(self):
        if self.name == "score-snap-tick":
            raise RuntimeError("can't start new thread")
        return real_thread_start(self)

    monkeypatch.setattr(threading.Thread, "start", raising_start)
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched

    with pytest.raises(RuntimeError):
        sched.start(immediate=True)

    assert ticks == []
    assert sched.liveness.snapshot().get("lifecycle") == "started"
    assert sched.state()["running"] is True
    assert sched._armed is False
    # Self-heal still works when the caller retries the arm:
    retry = sched.start(immediate=False)
    assert retry["started"] is True


class _StubLiveness:
    def __init__(self, snapshot: dict) -> None:
        self._snapshot = snapshot

    def snapshot(self) -> dict:
        return dict(self._snapshot)

    def start(self) -> None:
        self._snapshot["lifecycle"] = "started"

    def record_skip(self, reason: str) -> None:
        pass

    def record_failure(self, error: str = "", evidence=None) -> None:
        pass

    def record_success(self, evidence=None) -> None:
        pass


def test_revive_swap_lets_retired_scheduler_clobber_new_arm(tmp_path, monkeypatch):
    """Case 2 at 27f6b391: revive checks tick_in_progress/running under _lock,
    then swaps schedulers outside it. The old scheduler's tick thread is past
    its _is_registered() check at that moment; its late re-arm calls
    schedule_in_seconds(JOB_ID, ...) with replace_existing=True and replaces
    the NEW scheduler's pending tick — the new scheduler reports running while
    the only armed tick belongs to the retired instance."""
    _soul(tmp_path, monkeypatch)
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("WORKER_HEAVY", "essential")
    monkeypatch.delenv("STAGE2_HOP", raising=False)
    monkeypatch.setattr(
        snaps, "SCORE_SNAPSHOTS_PATH", str(tmp_path / "score_snapshots.json")
    )

    pending: dict = {}
    history: list = []

    def fake_schedule(job_id, func, seconds, **kw):
        history.append((job_id, func, seconds))
        pending[job_id] = {"func": func, "seconds": seconds}

    def fake_cancel(job_id):
        pending.pop(job_id, None)

    monkeypatch.setattr(snaps, "schedule_in_seconds", fake_schedule)
    monkeypatch.setattr(snaps, "cancel_job", fake_cancel)
    monkeypatch.setattr(
        snaps.ScoreSnapshotScheduler,
        "run_once",
        lambda self: {"ok": True, "run_at": "test"},
    )

    old = snaps.ScoreSnapshotScheduler()
    old.liveness = _StubLiveness({"lifecycle": "started", "status": "ok"})
    with snaps._lock:
        snaps._scheduler = old

    checked = threading.Event()
    release = threading.Event()
    original_is_registered = snaps.ScoreSnapshotScheduler._is_registered

    def parked_is_registered(self):
        result = original_is_registered(self)
        if self is old and not checked.is_set():
            checked.set()
            release.wait(5)
        return result

    monkeypatch.setattr(
        snaps.ScoreSnapshotScheduler, "_is_registered", parked_is_registered
    )

    # Old scheduler's tick in flight on the scoring_in_progress skip path:
    # _tick_active/_TICK_ACTIVE stay unset, so revive's tick_in_progress
    # check under _lock sees nothing in flight — but the thread is already
    # past the current-scheduler check it will act on after the swap.
    monkeypatch.setattr(
        snaps.ScoreSnapshotScheduler, "_scoring_in_progress", lambda self: True
    )
    t1 = threading.Thread(target=old._tick, kwargs={"reschedule": True}, daemon=True)
    t1.start()
    assert checked.wait(5)

    out = snaps.revive_score_snapshot_scheduler()
    release.set()
    t1.join(5)
    assert not t1.is_alive()

    new = snaps._scheduler
    assert new is not old
    assert out["recycled"] is True
    assert new.state()["running"] is True

    # Exactly two arms hit the shared JOB_ID: the new scheduler's start, then
    # the retired scheduler's late re-arm. replace_existing=True means the
    # second wins — the armed tick belongs to the RETIRED scheduler.
    assert [func.__self__ for _, func, _ in history] == [new, old]
    assert pending[snaps.JOB_ID]["func"].__self__ is old

    # Consequence: the next revive recycles the (now-current) new scheduler —
    # stop() cancels the one armed job, leaving it running with no tick
    # scheduled until the revive after that.
    snaps.stop_score_snapshot_scheduler()
    assert snaps.JOB_ID not in pending
    assert new.state()["running"] is True