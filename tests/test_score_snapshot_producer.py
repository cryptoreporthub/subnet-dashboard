"""PR-A / MC #1479 D1 — essential-worker producer boot + idempotency."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from internal.chain_read import ChainRead
from internal.council import score_snapshots as snaps
from internal.subnet_universe import UniverseSnapshot, _validity_entry
from tests.score_snapshot_testutil import _USABLE_SOUL_MAP, chain_read, complete_snapshot_payload


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


def test_essential_worker_boot_arms_scheduler_not_ensure(monkeypatch, tmp_path):
    """Replit #1484 P1: essential WORKER_HEAVY must arm producer, not score-snapshot-ensure."""
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("WORKER_HEAVY", "essential")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR_IS_VOLUME", "on")
    monkeypatch.setenv("SCORE_SNAPSHOT_BOOT_IMMEDIATE", "off")
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    defer_names: list[str] = []
    scheduled_jobs: list[str] = []

    def _defer(name, fn, delay=0):
        defer_names.append(name)
        if name == "score-snapshots":
            fn()

    monkeypatch.setattr("internal.background_boot.defer_boot", _defer)
    monkeypatch.setattr("internal.freshness.start_background_sync", MagicMock())
    monkeypatch.setattr(
        "internal.background_boot._start_pump_desk_snapshot_scheduler",
        MagicMock(),
    )
    for name in (
        "_start_pump_ladder",
        "_start_resolver",
        "_start_whale_warm_scheduler",
        "_start_pick_schedulers",
        "_maybe_start_message_intel",
        "_maybe_start_summary_bot",
        "_warm_judges_cache",
        "_start_pick_audit_scheduler",
        "_start_outcome_snapshot_scheduler",
        "_start_calibration_snapshot_scheduler",
        "_start_dev_radar_github_scheduler",
    ):
        monkeypatch.setattr(f"internal.background_boot.{name}", MagicMock())
    monkeypatch.setattr(snaps, "schedule_in_seconds", lambda job_id, _fn, _sec: scheduled_jobs.append(job_id))
    monkeypatch.setattr("internal.live_subnets.registry_ready", lambda: True)
    monkeypatch.setattr("internal.live_subnets.bootstrap_live_subnets_cache", MagicMock())
    monkeypatch.setattr("internal.live_subnets.start_live_subnets_sync", MagicMock())

    from internal.background_boot import start_background_workers

    start_background_workers()
    assert "score-snapshot-ensure" not in defer_names
    assert "score-snapshots" in defer_names
    assert snaps._scheduler is not None
    assert scheduled_jobs == [snaps.JOB_ID]


def test_second_start_in_process_does_not_spawn_a_second_tick(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    scheduled = []
    monkeypatch.setattr(
        snaps,
        "schedule_in_seconds",
        lambda job_id, func, seconds: scheduled.append((job_id, seconds)),
    )
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched
    first = sched.start(immediate=False)
    second = sched.start(immediate=False)
    assert first["started"] is True
    assert second["started"] is False
    assert second["reason"] == "already_armed"
    assert len(scheduled) == 1


def _isolated_soul(tmp_path, monkeypatch) -> None:
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))


def _fake_job_table(monkeypatch) -> dict:
    """Stand-in for the process-wide APScheduler: one slot per job id, replace on re-add."""
    jobs: dict = {}
    monkeypatch.setattr(
        snaps, "schedule_in_seconds", lambda job_id, fn, seconds: jobs.__setitem__(job_id, fn)
    )
    monkeypatch.setattr(snaps, "cancel_job", lambda job_id: jobs.pop(job_id, None))
    return jobs


def _record_snapshot_writes(monkeypatch) -> list:
    """Replace the scoring body's I/O so a tick that reaches it is observable."""
    writes: list = []

    def fake_write(progress_cb=None):
        writes.append(1)
        return {"ok": True, "published": True, "count": 1, "path": snaps.SCORE_SNAPSHOTS_PATH}

    monkeypatch.setattr(snaps, "write_full_universe_snapshot", fake_write)
    monkeypatch.setattr(snaps.ScoreSnapshotScheduler, "_persist_cycle_summary", lambda self, r: None)
    monkeypatch.setattr(snaps.ScoreSnapshotScheduler, "_clear_stuck_scoring", lambda self: None)
    monkeypatch.setattr(snaps.ScoreSnapshotScheduler, "_scoring_in_progress", lambda self: False)
    return writes


def _join_tick_threads() -> None:
    for t in threading.enumerate():
        if t.name == "score-snap-tick":
            t.join(timeout=5)
            assert not t.is_alive()


def test_stop_during_deferred_arm_leaves_no_pending_job(tmp_path, monkeypatch):
    """stop_score_snapshot_scheduler() during schedule_in_seconds must not leave JOB_ID armed."""
    _isolated_soul(tmp_path, monkeypatch)
    entered = threading.Event()
    release = threading.Event()
    jobs: dict = {}

    def gate_schedule(job_id, func, seconds):
        entered.set()
        if not release.wait(timeout=5):
            raise AssertionError("schedule gate timed out")
        jobs[job_id] = func

    monkeypatch.setattr(snaps, "schedule_in_seconds", gate_schedule)
    monkeypatch.setattr(snaps, "cancel_job", lambda job_id: jobs.pop(job_id, None))
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched
    start_result: dict = {}
    arm_thread = threading.Thread(
        target=lambda: start_result.update(sched.start(immediate=False)), name="test-deferred-arm"
    )
    arm_thread.start()
    assert entered.wait(timeout=5)
    # stop serializes behind the in-flight schedule call, so run it off-thread.
    stop_result: dict = {}
    stop_thread = threading.Thread(
        target=lambda: stop_result.update(snaps.stop_score_snapshot_scheduler()),
        name="test-stop",
    )
    stop_thread.start()
    # Release the gate only once stop has unregistered, so the arm must observe it.
    deadline = time.monotonic() + 5
    while True:
        with snaps._lock:
            if snaps._scheduler is None:
                break
        if time.monotonic() > deadline:
            release.set()
            pytest.fail("stop thread did not unregister the scheduler within 5s")
        time.sleep(0.005)
    release.set()
    arm_thread.join(timeout=5)
    stop_thread.join(timeout=5)
    assert not arm_thread.is_alive() and not stop_thread.is_alive()
    assert stop_result["stopped"] is True
    assert start_result["started"] is False
    assert start_result["reason"] == "stopped_during_arm"
    assert jobs == {}
    with snaps._lock:
        assert snaps._scheduler is None
    assert sched._armed is False
    assert sched.liveness.snapshot().get("lifecycle") != "started"


def test_aborted_arm_without_stop_leaves_no_pending_job(tmp_path, monkeypatch):
    """Reviewer P3-1: unregistered (no stop()) mid deferred arm -> job cancelled, disarmed."""
    _isolated_soul(tmp_path, monkeypatch)
    jobs = _fake_job_table(monkeypatch)
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched
    real_start = sched.liveness.start

    def unregister_then_start():
        # Job is already scheduled; drop registration without calling stop().
        with snaps._lock:
            snaps._scheduler = None
        return real_start()

    monkeypatch.setattr(sched.liveness, "start", unregister_then_start)
    result = sched.start(immediate=False)
    assert result == {"started": False, "reason": "stopped_during_arm"}
    assert jobs == {}
    assert snaps._job_owner is not sched
    assert sched._armed is False
    assert sched.liveness.snapshot().get("lifecycle") != "started"


def _persisted_lifecycle() -> str:
    from internal.store.soul_map_io import read_soul_map

    blob = read_soul_map(snaps._liveness_state_path()) or {}
    return str((blob.get("liveness") or {}).get("score_snapshot", {}).get("lifecycle"))


def test_aborted_old_scheduler_does_not_overwrite_replacement_persisted_liveness(
    tmp_path, monkeypatch
):
    """Replit P2: A defers, B starts and persists 'started', A aborts -> file still says started."""
    _isolated_soul(tmp_path, monkeypatch)
    _fake_job_table(monkeypatch)
    old, new = snaps.ScoreSnapshotScheduler(), snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = old
    paused, resume = threading.Event(), threading.Event()
    real_start = old._start_liveness

    def paused_start():
        # A has scheduled its job and is about to persist 'started'.
        paused.set()
        if not resume.wait(timeout=5):
            raise AssertionError("resume gate timed out")
        return real_start()

    monkeypatch.setattr(old, "_start_liveness", paused_start)
    old_result: dict = {}
    old_thread = threading.Thread(target=lambda: old_result.update(old.start(immediate=False)))
    old_thread.start()
    assert paused.wait(timeout=5)

    snaps.stop_score_snapshot_scheduler()
    with snaps._lock:
        snaps._scheduler = new
    assert new.start(immediate=False)["started"] is True
    assert _persisted_lifecycle() == "started"

    resume.set()
    old_thread.join(timeout=5)
    assert not old_thread.is_alive()
    assert old_result == {"started": False, "reason": "stopped_during_arm"}
    assert _persisted_lifecycle() == "started"
    assert new.liveness.snapshot().get("lifecycle") == "started"


def test_aborted_scheduler_without_replacement_still_persists_stopped(tmp_path, monkeypatch):
    """The fence must not stop an abort from recording 'stopped' when nobody replaced it."""
    _isolated_soul(tmp_path, monkeypatch)
    _fake_job_table(monkeypatch)
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched
    real_start = sched.liveness.start

    def unregister_then_start():
        with snaps._lock:
            snaps._scheduler = None
        return real_start()

    monkeypatch.setattr(sched.liveness, "start", unregister_then_start)
    assert sched.start(immediate=False) == {"started": False, "reason": "stopped_during_arm"}
    assert _persisted_lifecycle() == "stopped"


def test_failed_deferred_start_disarms_before_job_lock_is_released(tmp_path, monkeypatch):
    """Ditto Medium: a tick that takes _job_lock the moment cleanup releases it must not reschedule."""
    _isolated_soul(tmp_path, monkeypatch)
    jobs = _fake_job_table(monkeypatch)
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched

    class TickAfterRelease:
        """_job_lock stand-in: right after a release, a waiting tick gets the lock."""

        def __init__(self, real):
            self.real = real
            self.armed = False
            self.rescheduled = None

        def __enter__(self):
            self.real.acquire()

        def __exit__(self, *exc):
            self.real.release()
            if self.armed:
                self.armed = False
                self.rescheduled = sched._schedule_tick(5)

    gate = TickAfterRelease(snaps._job_lock)
    monkeypatch.setattr(snaps, "_job_lock", gate)

    def failing_liveness_start():
        gate.armed = True  # the next _job_lock release is the failed-start cleanup
        raise RuntimeError("liveness write failed")

    monkeypatch.setattr(sched.liveness, "start", failing_liveness_start)
    with pytest.raises(RuntimeError):
        sched.start(immediate=False)

    assert gate.rescheduled is False
    assert jobs == {}
    assert sched._armed is False
    assert snaps._job_owner is not sched


def _persisted_record() -> dict:
    from internal.store.soul_map_io import read_soul_map

    blob = read_soul_map(snaps._liveness_state_path()) or {}
    return dict((blob.get("liveness") or {}).get("score_snapshot") or {})


_PUBLISHED = {"ok": True, "published": True, "count": 7, "path": "/tmp/snap.json"}


def test_resumed_stale_start_cannot_wipe_replacement_health(tmp_path, monkeypatch):
    """Replit P2: A paused after scheduling, before its liveness start; stop A; B starts and
    records a success; A resumes -> B's success time, event time and evidence survive a reload."""
    _isolated_soul(tmp_path, monkeypatch)
    _fake_job_table(monkeypatch)
    old = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = old
    paused, resume = threading.Event(), threading.Event()
    real_start = old._start_liveness

    def paused_start():
        paused.set()
        if not resume.wait(timeout=5):
            raise AssertionError("resume gate timed out")
        return real_start()

    monkeypatch.setattr(old, "_start_liveness", paused_start)
    old_result: dict = {}
    old_thread = threading.Thread(target=lambda: old_result.update(old.start(immediate=False)))
    old_thread.start()
    assert paused.wait(timeout=5)

    snaps.stop_score_snapshot_scheduler()
    assert snaps.start_score_snapshot_scheduler(immediate=False)["started"] is True
    new = snaps._scheduler
    assert new is not old
    new._record_liveness(dict(_PUBLISHED))
    before = _persisted_record()
    assert before["lifecycle"] == "started"
    assert before["last_success_epoch"] is not None and before["last_event_epoch"] is not None
    assert before["last_evidence"]["count"] == 7

    resume.set()
    old_thread.join(timeout=5)
    assert not old_thread.is_alive()
    assert old_result == {"started": False, "reason": "stopped_during_arm"}
    after = _persisted_record()
    for key in ("lifecycle", "last_success_epoch", "last_event_epoch", "last_evidence", "updated_at"):
        assert after[key] == before[key], key


def test_stale_tick_skip_after_losing_ownership_is_not_persisted(tmp_path, monkeypatch):
    """Ditto: a tick loses ownership while _scoring_in_progress() runs, then records a skip."""
    _isolated_soul(tmp_path, monkeypatch)
    _fake_job_table(monkeypatch)
    _record_snapshot_writes(monkeypatch)
    old = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = old
    assert old.start(immediate=False)["started"] is True

    def lose_ownership_then_report_busy() -> bool:
        snaps.stop_score_snapshot_scheduler()
        assert snaps.start_score_snapshot_scheduler(immediate=False)["started"] is True
        snaps._scheduler._record_liveness(dict(_PUBLISHED))
        return True

    monkeypatch.setattr(old, "_scoring_in_progress", lose_ownership_then_report_busy)
    result = old._tick(reschedule=False)

    assert result["skipped"] == "scoring_in_progress"
    new = snaps._scheduler
    assert new is not old
    persisted = _persisted_record()
    assert persisted["consecutive_skips"] == 0
    assert persisted["last_success_epoch"] is not None
    assert persisted["lifecycle"] == "started"


def test_current_tick_skip_is_persisted(tmp_path, monkeypatch):
    """Control: the registered generation's skip still lands in the record."""
    _isolated_soul(tmp_path, monkeypatch)
    _fake_job_table(monkeypatch)
    _record_snapshot_writes(monkeypatch)
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched
    assert sched.start(immediate=False)["started"] is True
    monkeypatch.setattr(sched, "_scoring_in_progress", lambda: True)
    sched._tick(reschedule=False)
    assert _persisted_record()["consecutive_skips"] == 1


def test_clean_stop_persists_stopped(tmp_path, monkeypatch):
    """Ditto: stop_score_snapshot_scheduler() must not leave the persisted lifecycle 'started'."""
    _isolated_soul(tmp_path, monkeypatch)
    _fake_job_table(monkeypatch)
    assert snaps.start_score_snapshot_scheduler(immediate=False)["started"] is True
    assert _persisted_lifecycle() == "started"
    assert snaps.stop_score_snapshot_scheduler()["stopped"] is True
    assert _persisted_lifecycle() == "stopped"


def test_direct_stop_of_registered_scheduler_persists_stopped(tmp_path, monkeypatch):
    _isolated_soul(tmp_path, monkeypatch)
    _fake_job_table(monkeypatch)
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched
    assert sched.start(immediate=False)["started"] is True
    sched.stop()
    assert _persisted_lifecycle() == "stopped"


def test_stop_of_replaced_scheduler_does_not_persist(tmp_path, monkeypatch):
    """Control: an old generation's late stop() must leave the replacement's 'started' alone."""
    _isolated_soul(tmp_path, monkeypatch)
    _fake_job_table(monkeypatch)
    old = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = old
    assert old.start(immediate=False)["started"] is True
    with snaps._lock:
        snaps._scheduler = None
    assert snaps.start_score_snapshot_scheduler(immediate=False)["started"] is True
    new = snaps._scheduler
    new._record_liveness(dict(_PUBLISHED))
    before = _persisted_record()
    old.stop()
    assert _persisted_record() == before


@pytest.mark.parametrize("seed", range(6))
def test_storm_persisted_liveness_only_written_by_current_generation(tmp_path, monkeypatch, seed):
    """Randomized interleaving: no persisted liveness write ever comes from a replaced generation."""
    import random

    from internal.liveness import LivenessTracker

    _isolated_soul(tmp_path, monkeypatch)
    _fake_job_table(monkeypatch)
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("WORKER_HEAVY", "essential")
    generations: list = []
    real_init = snaps.ScoreSnapshotScheduler.__init__

    def tracking_init(self, *a, **kw):
        real_init(self, *a, **kw)
        generations.append(self)

    monkeypatch.setattr(snaps.ScoreSnapshotScheduler, "__init__", tracking_init)
    violations: list = []
    real_save = LivenessTracker._save

    def checking_save(self):
        if self.name == "score_snapshot":
            with snaps._lock:
                current = snaps._scheduler
            owner = next((g for g in list(generations) if g.liveness is self), None)
            if current is not None:
                if current is not owner:
                    violations.append("write from a replaced generation")
            elif snaps._last_registered is not owner:
                # Unregistered module: only the most recently registered generation may write.
                violations.append("write from a past generation while unregistered")
        return real_save(self)

    monkeypatch.setattr(LivenessTracker, "_save", checking_save)
    errors: list = []

    def worker(worker_seed: int) -> None:
        rng = random.Random(worker_seed)
        try:
            for i in range(60):
                op = rng.choice(["start", "stop", "record", "skip", "stale_start", "stale_stop"])
                gens = list(generations)
                gen = rng.choice(gens) if gens else None
                if op == "start":
                    snaps.start_score_snapshot_scheduler(immediate=False)
                elif op == "stop":
                    snaps.stop_score_snapshot_scheduler()
                elif gen is None:
                    continue
                elif op == "record":
                    gen._record_liveness({**_PUBLISHED, "count": i})
                elif op == "skip":
                    gen._record_liveness({"ok": False, "skipped": "scoring_in_progress"})
                elif op == "stale_start":
                    gen._start_liveness()
                else:
                    gen.stop()
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(seed * 10 + n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
        assert not t.is_alive()
    assert errors == []
    assert violations == []
    current = snaps._scheduler or snaps._last_registered
    if current is not None:
        persisted = _persisted_record()
        assert persisted["lifecycle"] == current.liveness.snapshot()["lifecycle"]


def _worker_env(monkeypatch) -> None:
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("WORKER_HEAVY", "essential")


def test_past_generation_cannot_write_after_a_newer_one_was_stopped(tmp_path, monkeypatch):
    """Reviewer P2: start A, success; stop A, start B, newer success; stop B (module is None);
    A's late result must not roll back B's newer success or add a failure."""
    _isolated_soul(tmp_path, monkeypatch)
    _fake_job_table(monkeypatch)
    _worker_env(monkeypatch)
    assert snaps.start_score_snapshot_scheduler(immediate=False)["started"] is True
    first = snaps._scheduler
    first._record_liveness(dict(_PUBLISHED))
    first_success = _persisted_record()["last_success_epoch"]
    time.sleep(0.02)
    snaps.stop_score_snapshot_scheduler()
    assert snaps.start_score_snapshot_scheduler(immediate=False)["started"] is True
    second = snaps._scheduler
    assert second is not first
    second._record_liveness(dict(_PUBLISHED))
    second_success = _persisted_record()["last_success_epoch"]
    assert second_success > first_success
    snaps.stop_score_snapshot_scheduler()
    assert snaps._scheduler is None
    before = _persisted_record()
    assert before["lifecycle"] == "stopped"

    first._record_liveness({"ok": False, "error": "ghost"})
    first.stop()

    assert _persisted_record() == before
    assert _persisted_record()["last_success_epoch"] == second_success
    assert _persisted_record()["consecutive_failures"] == 0


def test_most_recent_generation_may_still_record_after_unregistering(tmp_path, monkeypatch):
    """Control: a tick of the generation that was just stopped still lands its result."""
    _isolated_soul(tmp_path, monkeypatch)
    _fake_job_table(monkeypatch)
    _worker_env(monkeypatch)
    assert snaps.start_score_snapshot_scheduler(immediate=False)["started"] is True
    sched = snaps._scheduler
    snaps.stop_score_snapshot_scheduler()
    sched._record_liveness(dict(_PUBLISHED))
    assert _persisted_record()["last_success_epoch"] is not None


def test_replacement_cannot_register_while_old_generation_is_mid_write(tmp_path, monkeypatch):
    """Reviewer P3: registering a replacement (which loads the record) waits for the
    old generation's in-flight write, and then loads it."""
    _isolated_soul(tmp_path, monkeypatch)
    _fake_job_table(monkeypatch)
    _worker_env(monkeypatch)
    assert snaps.start_score_snapshot_scheduler(immediate=False)["started"] is True
    old = snaps._scheduler
    inside, go = threading.Event(), threading.Event()
    real_success = old.liveness.record_success

    def slow_success(evidence=None):
        inside.set()
        if not go.wait(timeout=5):
            raise AssertionError("write gate timed out")
        real_success(evidence=evidence)

    monkeypatch.setattr(old.liveness, "record_success", slow_success)
    writer = threading.Thread(target=lambda: old._record_liveness(dict(_PUBLISHED)))
    writer.start()
    assert inside.wait(timeout=5)
    with snaps._lock:
        snaps._scheduler = None  # what stop_score_snapshot_scheduler() does first
        snaps._last_registered = old
    started: dict = {}
    registrar = threading.Thread(
        target=lambda: started.update(result=snaps.start_score_snapshot_scheduler(immediate=False))
    )
    registrar.start()
    registrar.join(timeout=0.4)
    with snaps._lock:
        registered_mid_write = snaps._scheduler is not None
    go.set()
    writer.join(timeout=5)
    registrar.join(timeout=5)
    assert not writer.is_alive() and not registrar.is_alive()
    assert registered_mid_write is False
    new = snaps._scheduler
    assert new is not None and new is not old
    assert new.liveness.snapshot()["last_success_at"] is not None


def test_unarmed_strict_start_writes_nothing(tmp_path, monkeypatch):
    """Reviewer P3: a registered but disarmed generation must not persist 'started'."""
    _isolated_soul(tmp_path, monkeypatch)
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched
    assert sched._armed is False
    assert sched._start_liveness() is False
    assert _persisted_record() == {}
    sched._armed = True
    assert sched._start_liveness() is True
    assert _persisted_lifecycle() == "started"


def test_liveness_write_happens_while_holding_the_lifecycle_lock(tmp_path, monkeypatch):
    """Reviewer P3: the ownership check and the write are one critical section."""
    _isolated_soul(tmp_path, monkeypatch)
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched
    held: list = []
    real_success = sched.liveness.record_success

    def watching_success(evidence=None):
        held.append(snaps._lifecycle_lock.locked())
        real_success(evidence=evidence)

    monkeypatch.setattr(sched.liveness, "record_success", watching_success)
    sched._record_liveness(dict(_PUBLISHED))
    assert held == [True]


def test_scheduler_is_constructed_without_the_global_lock(tmp_path, monkeypatch):
    """Reviewer P3: the tracker reads the liveness file during construction; the global
    _lock must not be held across that read."""
    _isolated_soul(tmp_path, monkeypatch)
    _fake_job_table(monkeypatch)
    _worker_env(monkeypatch)
    observed: list = []
    real_init = snaps.ScoreSnapshotScheduler.__init__

    def watching_init(self, *a, **kw):
        observed.append((snaps._lock.locked(), snaps._lifecycle_lock.locked()))
        real_init(self, *a, **kw)

    monkeypatch.setattr(snaps.ScoreSnapshotScheduler, "__init__", watching_init)
    assert snaps.start_score_snapshot_scheduler(immediate=False)["started"] is True
    assert observed == [(False, True)]


def test_stale_arm_cannot_cancel_replacement_scheduler_job(tmp_path, monkeypatch):
    """Replit P2 #1 / Ditto L1328: stop A, start B, resume A -> B's job survives and B ticks."""
    _isolated_soul(tmp_path, monkeypatch)
    jobs = _fake_job_table(monkeypatch)
    writes = _record_snapshot_writes(monkeypatch)
    old, new = snaps.ScoreSnapshotScheduler(), snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = old
    paused, resume = threading.Event(), threading.Event()
    real_snapshot = old.liveness.snapshot

    def paused_snapshot():
        # Pause only start()'s read; stop() also reads the snapshot when it persists.
        if not paused.is_set():
            paused.set()
            if not resume.wait(timeout=5):
                raise AssertionError("resume gate timed out")
        return real_snapshot()

    monkeypatch.setattr(old.liveness, "snapshot", paused_snapshot)
    old_result: dict = {}
    old_thread = threading.Thread(target=lambda: old_result.update(old.start(immediate=False)))
    old_thread.start()
    assert paused.wait(timeout=5)  # old start is armed-flagged but has not scheduled yet

    snaps.stop_score_snapshot_scheduler()
    with snaps._lock:
        snaps._scheduler = new
    assert new.start(immediate=False)["started"] is True
    new_job = jobs[snaps.JOB_ID]

    resume.set()
    old_thread.join(timeout=5)
    assert not old_thread.is_alive()
    assert old_result == {"started": False, "reason": "stopped_during_arm"}
    assert jobs.get(snaps.JOB_ID) == new_job
    assert new._armed is True
    assert new.liveness.snapshot().get("lifecycle") == "started"
    jobs[snaps.JOB_ID]()
    assert writes == [1]


def test_stop_of_unregistered_scheduler_keeps_replacement_job(tmp_path, monkeypatch):
    """stop_score_snapshot_scheduler() unregisters before it calls stop(); a replacement
    that arms in that gap owns JOB_ID, and the old stop() must not cancel it."""
    _isolated_soul(tmp_path, monkeypatch)
    jobs = _fake_job_table(monkeypatch)
    old, new = snaps.ScoreSnapshotScheduler(), snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = old
    assert old.start(immediate=False)["started"] is True
    with snaps._lock:
        snaps._scheduler = new  # old is unregistered; its stop() has not run yet
    assert new.start(immediate=False)["started"] is True
    new_job = jobs[snaps.JOB_ID]

    old.stop()

    assert jobs.get(snaps.JOB_ID) == new_job
    assert new._armed is True


def test_dispatched_tick_of_stopped_scheduler_neither_publishes_nor_rearms(tmp_path, monkeypatch):
    """Ditto L1364: a callback already handed to the executor before stop() runs afterwards."""
    _isolated_soul(tmp_path, monkeypatch)
    jobs = _fake_job_table(monkeypatch)
    writes = _record_snapshot_writes(monkeypatch)
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched
    assert sched.start(immediate=False)["started"] is True
    dispatched = jobs[snaps.JOB_ID]
    sched.stop()
    assert jobs == {}

    dispatched()

    assert writes == []
    assert jobs == {}


def test_stop_during_immediate_arm_skips_tick_body(tmp_path, monkeypatch):
    """stop during immediate start must not run _tick_body or leave liveness started."""
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(tmp_path / "score_snapshots.json"))
    monkeypatch.setattr(snaps, "schedule_in_seconds", lambda *a, **k: None)
    entered = threading.Event()
    release = threading.Event()
    tick_bodies: list = []
    real_thread_start = snaps.threading.Thread.start

    def gate_thread_start(self):
        if self.name == "score-snap-tick":
            entered.set()
            if not release.wait(timeout=5):
                raise AssertionError("immediate arm gate timed out")
        real_thread_start(self)

    monkeypatch.setattr(snaps.threading.Thread, "start", gate_thread_start)
    monkeypatch.setattr(
        snaps.ScoreSnapshotScheduler,
        "_tick_body",
        lambda self, reschedule=True, **_kw: tick_bodies.append(1)
        or {"ok": False, "skipped": "test"},
    )
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched
    start_result: dict = {}

    def arm():
        start_result.update(sched.start(immediate=True))

    arm_thread = threading.Thread(target=arm, name="test-immediate-arm")
    arm_thread.start()
    assert entered.wait(timeout=5)
    stop_result = snaps.stop_score_snapshot_scheduler()
    assert stop_result["stopped"] is True
    release.set()
    arm_thread.join(timeout=5)
    assert not arm_thread.is_alive()
    assert start_result["started"] is False
    assert start_result["reason"] == "stopped_during_arm"
    assert tick_bodies == []
    assert sched.liveness.snapshot().get("lifecycle") != "started"
    with snaps._lock:
        assert snaps._scheduler is None


def test_stop_between_immediate_tick_admission_check_and_body_publishes_nothing(tmp_path, monkeypatch):
    """Replit P2 #2 / Ditto L1500: stop lands after the tick's last validity check but
    before the body claims the active slot; the aborted start must not publish."""
    _isolated_soul(tmp_path, monkeypatch)
    jobs = _fake_job_table(monkeypatch)
    writes = _record_snapshot_writes(monkeypatch)
    real_body = snaps.ScoreSnapshotScheduler._tick_body

    def stop_then_enter_body(self, *args, **kwargs):
        snaps.stop_score_snapshot_scheduler()
        return real_body(self, *args, **kwargs)

    monkeypatch.setattr(snaps.ScoreSnapshotScheduler, "_tick_body", stop_then_enter_body)
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched

    sched.start(immediate=True)
    _join_tick_threads()

    assert writes == []
    assert jobs == {}
    assert snaps._TICK_ACTIVE is False
    assert sched._armed is False


def test_failed_arm_leaves_scheduler_retryable(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    scheduled = []

    def flaky_schedule(job_id, func, seconds):
        if not scheduled:
            scheduled.append("failed")
            raise RuntimeError("scheduler unavailable")
        scheduled.append((job_id, seconds))

    monkeypatch.setattr(snaps, "schedule_in_seconds", flaky_schedule)
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched
    with pytest.raises(RuntimeError):
        sched.start(immediate=False)
    retry = sched.start(immediate=False)
    assert retry["started"] is True
    assert scheduled[-1][0] == snaps.JOB_ID


def test_failed_arm_rolls_back_even_when_cancel_raises(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    arms = []
    cancels = []
    monkeypatch.setattr(snaps, "schedule_in_seconds", lambda job_id, fn, seconds: arms.append(job_id))

    def flaky_cancel(job_id):
        cancels.append(job_id)
        if len(cancels) == 1:
            raise RuntimeError("cancel unavailable")

    monkeypatch.setattr(snaps, "cancel_job", flaky_cancel)
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched
    real_start = sched.liveness.start
    liveness_calls = []

    def flaky_liveness_start():
        liveness_calls.append(1)
        if len(liveness_calls) == 1:
            raise RuntimeError("liveness persist unavailable")
        return real_start()

    monkeypatch.setattr(sched.liveness, "start", flaky_liveness_start)
    with pytest.raises(RuntimeError, match="cancel unavailable|liveness persist unavailable"):
        sched.start(immediate=False)
    assert sched._armed is False
    retry = sched.start(immediate=False)
    assert retry["started"] is True
    assert arms == [snaps.JOB_ID, snaps.JOB_ID]


def test_failed_arm_does_not_report_running(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))

    def failing_schedule(job_id, func, seconds):
        raise RuntimeError("scheduler unavailable")

    monkeypatch.setattr(snaps, "schedule_in_seconds", failing_schedule)
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched
    with pytest.raises(RuntimeError):
        sched.start(immediate=False)
    assert sched.state()["running"] is False


def test_failed_liveness_start_in_immediate_mode_runs_no_tick(tmp_path, monkeypatch):
    """Caveat on 3b05bf26: in immediate mode the tick thread starts before
    liveness.start(). If the liveness write raises, cancel_job cannot stop a
    thread that is already running, so a failed arm may still leave a live tick."""
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    path = tmp_path / "score_snapshots.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    scheduled: list = []
    monkeypatch.setattr(snaps, "schedule_in_seconds", lambda job_id, fn, sec: scheduled.append((job_id, fn)))
    ticks: list = []
    monkeypatch.setattr(
        snaps.ScoreSnapshotScheduler,
        "_tick",
        lambda self, reschedule=True: ticks.append(1) or {"ok": False, "skipped": "test"},
    )
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched
    liveness_calls = {"n": 0}

    def failing_start():
        liveness_calls["n"] += 1
        if liveness_calls["n"] == 1:
            time.sleep(0.05)  # widen the window for an (incorrectly) started tick thread
            raise RuntimeError("liveness persist unavailable")

    monkeypatch.setattr(sched.liveness, "start", failing_start)
    with pytest.raises(RuntimeError):
        sched.start(immediate=True)

    time.sleep(0.5)
    assert ticks == []
    assert path.exists() is False
    assert sched.state()["running"] is False
    retry = sched.start(immediate=False)
    assert retry["started"] is True
    assert [job_id for job_id, _ in scheduled] == [snaps.JOB_ID]


def test_failed_tick_thread_start_in_immediate_mode_does_not_leave_started_lifecycle(tmp_path, monkeypatch):
    """Liveness is marked started before the tick thread exists. If the thread
    cannot start, the lifecycle must not stay ``started``: revive reads that as
    a running scheduler with no tick behind it."""
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(tmp_path / "score_snapshots.json"))
    monkeypatch.setattr(snaps, "schedule_in_seconds", lambda job_id, fn, sec: None)
    ticks: list = []
    monkeypatch.setattr(
        snaps.ScoreSnapshotScheduler,
        "_tick",
        lambda self, reschedule=True: ticks.append(1) or {"ok": False, "skipped": "test"},
    )
    real_thread = snaps.threading.Thread

    class TickThreadCannotStart(real_thread):
        def start(self):
            if self.name == "score-snap-tick":
                raise RuntimeError("cannot start thread")
            super().start()

    monkeypatch.setattr(snaps.threading, "Thread", TickThreadCannotStart)
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched

    with pytest.raises(RuntimeError):
        sched.start(immediate=True)

    assert ticks == []
    assert sched.liveness.snapshot()["lifecycle"] == "stopped"
    assert sched.state()["running"] is False


@pytest.mark.parametrize("bad_epoch", ["Infinity", "NaN", "1e300"])
def test_corrupt_persisted_epoch_does_not_make_start_raise(tmp_path, monkeypatch, bad_epoch):
    """A non-finite or out-of-range epoch in persisted liveness state must not
    escape ``start()``: the corrupt value is reported as unknown, not raised."""
    soul = tmp_path / "soul_map.json"
    soul.write_text(
        '{"liveness": {"score_snapshot": {"last_success_epoch": %s,'
        ' "last_event_epoch": %s, "lifecycle": "stopped"}}}' % (bad_epoch, bad_epoch),
        encoding="utf-8",
    )
    liveness_file = tmp_path / "score_snapshot_liveness.json"
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    monkeypatch.setattr(
        "internal.council.scheduler_cycle_state.liveness_state_path",
        lambda: str(liveness_file),
    )
    monkeypatch.setattr(snaps, "schedule_in_seconds", lambda job_id, fn, sec: None)
    sched = snaps.ScoreSnapshotScheduler()
    with snaps._lock:
        snaps._scheduler = sched

    result = sched.start(immediate=False)

    assert result["started"] is True
    live = sched.state()["liveness"]
    assert live["last_success_at"] is None
    assert live["last_event_at"] is None
    assert live["status"] == "no_success_yet"
    assert live["success_age_seconds"] is None
    assert live["event_age_seconds"] is None
    persisted = json.loads(liveness_file.read_text(encoding="utf-8"))
    assert persisted["liveness"]["score_snapshot"]["lifecycle"] == "started"


def _membership_for_netuids(netuids: range) -> UniverseSnapshot:
    resolved = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rows = tuple(
        {
            "netuid": n,
            "name": f"s{n}",
            "price": 1.0,
            "volume": 1000.0,
            "source": "taomarketcap",
        }
        for n in netuids
    )
    validity = {str(n): _validity_entry(validity="positive", sources=["taomarketcap"]) for n in netuids}
    return UniverseSnapshot(
        netuids=tuple(netuids),
        rows=rows,
        resolved_at=resolved,
        status="ok",
        degraded=False,
        cap_reached=False,
        refresh_incomplete=False,
        validity_map=validity,
        chain=chain_read(netuids),
    )


def _essential_worker_cycle_fixtures(tmp_path, monkeypatch, membership, seed_path, *, scheduled=None, soul=None):
    """Shared fixture set so a real cycle can run without chain or heavy-job access."""
    monkeypatch.setenv("SCORE_SNAPSHOT_CYCLE_PATH", str(tmp_path / "cycle.json"))
    monkeypatch.setenv("SCORE_SNAPSHOT_REGISTRY_ONLY", "on")
    monkeypatch.setenv("SCORE_SNAPSHOT_BOOT_IMMEDIATE", "off")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("WORKER_HEAVY", "essential")
    monkeypatch.setattr("internal.subnet_universe.get_snapshot", lambda: membership)
    from internal.council import snapshot_coverage as cov

    monkeypatch.setattr(cov, "coverage_capture_deadline_seconds", lambda _start: True)

    def _day(sn, _ctx):
        return {"total_score": float(sn["netuid"])}

    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_day", _day)
    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_hour", _day)
    monkeypatch.setattr(snaps, "_score_hour_enabled", lambda: False)
    hydrate = [{"netuid": n, "name": f"s{n}", "price": 1.0, "volume": 1000.0} for n in membership.netuids]
    monkeypatch.setattr("server._get_subnets_hydrate", lambda: (hydrate, "registry-fallback"))

    def _capture(job_id, fn, seconds):
        if scheduled is not None:
            scheduled.append((job_id, fn))

    monkeypatch.setattr(snaps, "schedule_in_seconds", _capture)
    monkeypatch.setattr(snaps.ScoreSnapshotScheduler, "_scoring_in_progress", lambda self: False)
    soul_path = tmp_path / "soul_map.json"
    merged_soul = {**_USABLE_SOUL_MAP, **(soul if soul is not None else {})}
    soul_path.write_text(json.dumps(merged_soul), encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul_path))
    return soul_path


@pytest.mark.parametrize("seed_only", [False, True], ids=["stale_volume_file", "seed_only_no_volume_file"])
def test_essential_worker_boot_publishes_complete_snapshot(tmp_path, monkeypatch, seed_only):
    netuids = range(1, 129)
    membership = _membership_for_netuids(netuids)
    path = tmp_path / "score_snapshots.json"
    old_started = "2020-01-01T00:00:00Z"
    seed_rows = [{"netuid": n, "total_score": float(n)} for n in (1, 2, 3)]
    payload = complete_snapshot_payload(day_rows=seed_rows, hour_rows=seed_rows)
    payload["build_started_at"] = old_started
    seed_path = tmp_path / "seed.json" if seed_only else tmp_path / "no_seed.json"
    (seed_path if seed_only else path).write_text(json.dumps(payload), encoding="utf-8")
    assert path.exists() is not seed_only
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(seed_path))
    _essential_worker_cycle_fixtures(
        tmp_path,
        monkeypatch,
        membership,
        seed_path,
        soul={"score_snapshot_scheduler": {"last_cycle": {"phase": "done", "ok": True}}},
    )

    score_boot_ran = {"n": 0}

    def _defer(name, fn, delay=0):
        if name == "score-snapshots":
            score_boot_ran["n"] += 1
            fn()

    monkeypatch.setattr("internal.background_boot.defer_boot", _defer)
    from internal.background_boot import _start_score_snapshot_scheduler

    _start_score_snapshot_scheduler()
    assert score_boot_ran["n"] == 1
    sched = snaps._scheduler
    assert sched is not None
    assert sched.liveness.snapshot().get("lifecycle") == "started"
    out = sched.run_once()
    assert out.get("ok") is True
    assert out.get("complete") is True
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["coverage"]["complete"] is True
    assert on_disk.get("build_started_at") and on_disk["build_started_at"] != old_started
    assert on_disk["count"] == len(netuids)


def test_restart_with_fresh_snapshot_and_persisted_started_lifecycle_still_arms(tmp_path, monkeypatch):
    """Replit P1 (restart arming): a fresh complete volume file plus a persisted
    lifecycle=started must not keep the producer from re-arming after a restart.
    The ``start()`` returns early when the served state is FRESH mutation must fail here."""
    netuids = range(1, 129)
    membership = _membership_for_netuids(netuids)
    path = tmp_path / "score_snapshots.json"
    fresh_started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    day_rows = [{"netuid": n, "total_score": float(n)} for n in netuids]
    payload = complete_snapshot_payload(day_rows=day_rows, hour_rows=day_rows)
    payload["build_started_at"] = fresh_started
    path.write_text(json.dumps(payload), encoding="utf-8")
    seed_path = tmp_path / "no_seed.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(seed_path))
    scheduled: list = []
    _essential_worker_cycle_fixtures(
        tmp_path,
        monkeypatch,
        membership,
        seed_path,
        scheduled=scheduled,
        soul={
            "liveness": {
                "score_snapshot": {
                    "last_success_epoch": datetime.now(timezone.utc).timestamp(),
                    "last_event_epoch": datetime.now(timezone.utc).timestamp(),
                    "lifecycle": "started",
                    "consecutive_failures": 0,
                    "consecutive_skips": 0,
                    "last_error": None,
                    "last_evidence": {"count": len(netuids), "op": "score_snapshot"},
                    "updated_at": fresh_started,
                }
            },
            "score_snapshot_scheduler": {"last_cycle": {"phase": "done", "ok": True}},
        },
    )

    served = snaps.read_served_snapshot(path=str(path), seed_path=str(seed_path))
    assert served.state is snaps.ServedState.FRESH
    persisted = json.loads((tmp_path / "soul_map.json").read_text(encoding="utf-8"))
    assert persisted["liveness"]["score_snapshot"]["lifecycle"] == "started"

    def _defer(name, fn, delay=0):
        if name == "score-snapshots":
            fn()

    monkeypatch.setattr("internal.background_boot.defer_boot", _defer)
    from internal.background_boot import _start_score_snapshot_scheduler

    _start_score_snapshot_scheduler()
    sched = snaps._scheduler
    assert sched is not None
    assert [job_id for job_id, _ in scheduled] == [snaps.JOB_ID]
    assert sched.state()["running"] is True

    tick_fn = scheduled[0][1]
    tick_fn()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["coverage"]["complete"] is True
    assert on_disk["build_started_at"] != fresh_started
    assert on_disk["count"] == len(netuids)


def _stale_volume_file(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "score_snapshots.json"
    payload = complete_snapshot_payload()
    payload["build_started_at"] = "2020-01-01T00:00:00Z"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return path


@pytest.mark.parametrize(
    "env,revived",
    [
        ({"WORKER_HEAVY": "off"}, False),
        ({"STAGE2_HOP": "1", "WORKER_HEAVY": "essential"}, False),
        ({"WORKER_HEAVY": "essential"}, True),
    ],
    ids=["heavy_off", "hop", "essential_owner"],
)
def test_revive_runs_only_on_the_producer_owner(tmp_path, monkeypatch, env, revived):
    """MC blocker: stall-guard revive must not make a non-owner worker produce."""
    path = _stale_volume_file(tmp_path, monkeypatch)
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.delenv("STAGE2_HOP", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    ticks: list[int] = []
    monkeypatch.setattr(
        snaps.ScoreSnapshotScheduler,
        "run_once",
        lambda self: ticks.append(1) or {"ok": True, "skipped": True},
    )
    monkeypatch.setattr(snaps, "schedule_in_seconds", lambda *a, **k: None)

    out = snaps.revive_score_snapshot_scheduler()

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    if revived:
        assert ticks == [1]
        assert out["start"]["started"] is True
    else:
        assert ticks == []
        assert out["revived"] is False
        assert out["reason"] == "not_owner"
        assert snaps._scheduler is None
        assert snaps.start_score_snapshot_scheduler()["reason"] == "not_owner"
