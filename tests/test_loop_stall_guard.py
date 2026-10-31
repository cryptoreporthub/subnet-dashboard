"""Loop stall guard — probe/revive must target score_snapshots.json producer."""

from __future__ import annotations

import json
from datetime import datetime, timezone
import logging

import os
import threading
import time
from pathlib import Path

import pytest

from internal import loop_stall_guard
from internal.council import score_snapshots as snaps
from internal.learning import loop_health
from internal.loop_stall_guard import MAX_SNAPSHOT_AGE_SECONDS, _try_revive
from tests.score_snapshot_testutil import complete_snapshot_payload


def _make_stale_snapshot(path, *, age_seconds: float = 100_000) -> None:
    old_iso = "2020-01-01T00:00:00Z"
    path.write_text(
        json.dumps(
            complete_snapshot_payload(
                day_rows=[{"netuid": 1, "total_score": 1.0}],
                written_at=old_iso,
            )
        ),
        encoding="utf-8",
    )
    old = time.time() - age_seconds
    os.utime(path, (old, old))


def _wire_snapshot_paths(tmp_path, monkeypatch):
    snap_path = tmp_path / "score_snapshots.json"
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(snap_path))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "no_seed.json"))
    monkeypatch.setenv("SCORE_SNAPSHOTS_PATH", str(snap_path))
    monkeypatch.setattr(loop_health, "SCORE_SNAPSHOTS_PATH", str(snap_path))
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    # Fixtures read the weights digest through the soul_map cache; a test that rewrites soul_map must see the file.
    monkeypatch.setattr("internal.store.soul_map_io._CACHE_TTL", 0)
    return snap_path



def _seed_degraded_status(tracker, status: str) -> None:
    """Force liveness status to failing/stale/starved without changing lifecycle."""
    if status == "failing":
        tracker.record_success(evidence={"scanned": 1})
        tracker.record_failure("boom")
    elif status == "stale":
        tracker.record_success(evidence={"scanned": 1})
        tracker._last_success_epoch -= (
            tracker.interval_seconds * tracker.staleness_factor + 10
        )
    elif status == "starved":
        tracker.record_success(evidence={"scanned": 1})
        tracker._last_success_epoch -= (
            tracker.interval_seconds * tracker.staleness_factor + 10
        )
        for _ in range(tracker.skip_limit):
            tracker.record_skip("heavy_job_busy")
    else:
        raise AssertionError(f"unexpected degraded status {status!r}")
    assert tracker.snapshot()["status"] == status, tracker.snapshot()


def test_p4b_calibrated_default_thresholds():
    """Prod soak4 evidence: see docs/ops/loop-stall-guard-calibration-2026-10-10.md."""
    assert loop_stall_guard.CONSECUTIVE_CHECKS >= 3
    assert loop_stall_guard.RESOLVER_REVIVE_AFTER_SECONDS >= 2400
    assert loop_stall_guard.KILL_ENABLED is True  # unchanged; do not unmute via defaults


def test_probe_failures_are_warning_level_and_fail_closed(monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="internal.loop_stall_guard")

    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("WORKER_HEAVY", "essential")
    monkeypatch.delenv("STAGE2_HOP", raising=False)
    monkeypatch.delenv("SCORE_SNAPSHOT_SCHEDULER_ENABLED", raising=False)

    def _boom(*_a, **_k):
        raise RuntimeError("receipt probe exploded")

    monkeypatch.setattr(snaps, "producer_cycle_age_seconds", _boom)
    assert loop_stall_guard._snapshot_age_seconds() is None

    monkeypatch.delattr(loop_health, "_last_resolver_tick", raising=False)
    assert loop_stall_guard._resolver_tick_age_seconds() is None

    messages = [record.getMessage() for record in caplog.records]
    assert any("snapshot age probe failed" in message for message in messages)
    assert any("resolver tick probe failed" in message for message in messages)
    assert all(record.levelno == logging.WARNING for record in caplog.records)


def _fake_write_that_saves(snap_path):
    def _fake_write(progress_cb=None):
        if progress_cb:
            progress_cb(1, 1)
        snaps.publish_complete_snapshot(
            complete_snapshot_payload(
                day_rows=[{"netuid": 1, "total_score": 1.0}],
                written_at=snaps._now_iso(),
            ),
            str(snap_path),
        )
        return {
            "ok": True,
            "count": 1,
            "written_at": "2026-08-21T00:00:00Z",
            "path": str(snap_path),
        }

    return _fake_write


def test_revive_resets_stale_snapshot_age(tmp_path, monkeypatch):
    snap_path = _wire_snapshot_paths(tmp_path, monkeypatch)
    _make_stale_snapshot(snap_path)
    monkeypatch.setattr(snaps, "write_full_universe_snapshot", _fake_write_that_saves(snap_path))

    age_before = loop_health._snapshot_age_seconds(str(snap_path))
    assert age_before is not None
    assert age_before > 5000

    try:
        out = snaps.revive_score_snapshot_scheduler()
        assert out["revived"] is True
        age_after = loop_health._snapshot_age_seconds(str(snap_path))
        assert age_after is not None
        assert age_after < 60
        assert age_after < age_before
    finally:
        snaps.stop_score_snapshot_scheduler()


def test_try_revive_targets_score_snapshot_scheduler(tmp_path, monkeypatch):
    snap_path = _wire_snapshot_paths(tmp_path, monkeypatch)
    _make_stale_snapshot(snap_path)
    monkeypatch.setattr(snaps, "write_full_universe_snapshot", _fake_write_that_saves(snap_path))

    # Simulate alive-but-hung: lifecycle claims started but file never updates.
    snaps.stop_score_snapshot_scheduler()
    sched = snaps.ScoreSnapshotScheduler()
    sched.liveness.start()
    snaps._scheduler = sched

    age_before = loop_health._snapshot_age_seconds(str(snap_path))
    assert age_before > 5000

    try:
        _try_revive()
        age_after = loop_health._snapshot_age_seconds(str(snap_path))
        assert age_after is not None
        assert age_after < 60
        assert age_after < age_before
    finally:
        snaps.stop_score_snapshot_scheduler()


def test_revive_recycles_running_scheduler_in_guard_age_window(tmp_path, monkeypatch):
    """5400–7200s window: guard already stale; recycle when lifecycle claims started."""
    snap_path = _wire_snapshot_paths(tmp_path, monkeypatch)
    guard_stale_age = MAX_SNAPSHOT_AGE_SECONDS + 100
    assert guard_stale_age < snaps.SCORE_SNAPSHOT_MAX_AGE_SECONDS
    _make_stale_snapshot(snap_path, age_seconds=guard_stale_age)
    monkeypatch.setattr(snaps, "write_full_universe_snapshot", _fake_write_that_saves(snap_path))

    snaps.stop_score_snapshot_scheduler()
    sched = snaps.ScoreSnapshotScheduler()
    sched.liveness.start()
    snaps._scheduler = sched

    age_before = loop_health._snapshot_age_seconds(str(snap_path))
    assert age_before > MAX_SNAPSHOT_AGE_SECONDS

    try:
        out = snaps.revive_score_snapshot_scheduler()
        assert out["recycled"] is True
        assert out["revived"] is True
        age_after = loop_health._snapshot_age_seconds(str(snap_path))
        assert age_after is not None
        assert age_after < 60
        assert age_after < age_before
    finally:
        snaps.stop_score_snapshot_scheduler()


def test_revive_recycles_very_stale_running_scheduler(tmp_path, monkeypatch):
    snap_path = _wire_snapshot_paths(tmp_path, monkeypatch)
    _make_stale_snapshot(snap_path, age_seconds=snaps.SCORE_SNAPSHOT_MAX_AGE_SECONDS + 100)
    monkeypatch.setattr(snaps, "write_full_universe_snapshot", _fake_write_that_saves(snap_path))

    snaps.stop_score_snapshot_scheduler()
    sched = snaps.ScoreSnapshotScheduler()
    sched.liveness.start()
    snaps._scheduler = sched

    try:
        out = snaps.revive_score_snapshot_scheduler()
        assert out["recycled"] is True
        assert out["revived"] is True
        age_after = loop_health._snapshot_age_seconds(str(snap_path))
        assert age_after is not None
        assert age_after < 60
    finally:
        snaps.stop_score_snapshot_scheduler()


def test_revive_honest_when_tick_in_progress(tmp_path, monkeypatch):
    snap_path = _wire_snapshot_paths(tmp_path, monkeypatch)
    _make_stale_snapshot(snap_path)
    write_calls = {"n": 0}
    tick_started = threading.Event()
    release_tick = threading.Event()

    def _slow_write(progress_cb=None):
        write_calls["n"] += 1
        tick_started.set()
        release_tick.wait(timeout=5)
        return _fake_write_that_saves(snap_path)(progress_cb)

    monkeypatch.setattr(snaps, "write_full_universe_snapshot", _slow_write)

    snaps.stop_score_snapshot_scheduler()
    sched = snaps.ScoreSnapshotScheduler()
    sched.liveness.start()
    sched._scoring_in_progress = lambda: False
    snaps._scheduler = sched

    age_before = loop_health._snapshot_age_seconds(str(snap_path))
    tick_thread = threading.Thread(
        target=sched._tick_body,
        kwargs={"reschedule": False},
        daemon=True,
    )
    tick_thread.start()
    assert tick_started.wait(timeout=5)

    try:
        out = snaps.revive_score_snapshot_scheduler()
        assert out["revived"] is False
        assert out.get("reason") == "tick_in_progress"
        assert write_calls["n"] == 1
        age_after = loop_health._snapshot_age_seconds(str(snap_path))
        assert age_after is not None
        assert age_after >= age_before - 1
    finally:
        release_tick.set()
        tick_thread.join(timeout=5)
        snaps._TICK_ACTIVE = False
        snaps.stop_score_snapshot_scheduler()


def test_revive_false_when_file_already_young_and_no_write(tmp_path, monkeypatch):
    """Young mtime + ok tick without publish_complete_snapshot must not claim revived."""
    snap_path = _wire_snapshot_paths(tmp_path, monkeypatch)
    snap_path.write_text('{"day":[],"hour":[]}', encoding="utf-8")
    age_before = loop_health._snapshot_age_seconds(str(snap_path))
    assert age_before is not None
    assert age_before < 60

    monkeypatch.setattr(
        snaps,
        "write_full_universe_snapshot",
        lambda progress_cb=None: {
            "ok": True,
            "count": 0,
            "written_at": "2026-08-21T00:00:00Z",
            "path": str(snap_path),
        },
    )

    try:
        out = snaps.revive_score_snapshot_scheduler()
        assert out["revived"] is False
        age_after = loop_health._snapshot_age_seconds(str(snap_path))
        assert age_after is not None
        assert age_after >= age_before - 1
    finally:
        snaps.stop_score_snapshot_scheduler()


def test_revive_false_on_skip_or_ok_without_file_write(tmp_path, monkeypatch):
    snap_path = _wire_snapshot_paths(tmp_path, monkeypatch)
    _make_stale_snapshot(snap_path)

    def _skip_only(progress_cb=None):
        return {"ok": True, "skipped": "heavy_job_busy", "run_at": "2026-08-21T00:00:00Z"}

    monkeypatch.setattr(snaps, "write_full_universe_snapshot", _skip_only)

    try:
        out = snaps.revive_score_snapshot_scheduler()
        assert out["revived"] is False
        age_after = loop_health._snapshot_age_seconds(str(snap_path))
        assert age_after is not None
        assert age_after > 5000
    finally:
        snaps.stop_score_snapshot_scheduler()


def test_revive_false_on_ok_without_moving_mtime(tmp_path, monkeypatch):
    """ok:True without publish_complete_snapshot must not count as revived."""
    snap_path = _wire_snapshot_paths(tmp_path, monkeypatch)
    _make_stale_snapshot(snap_path, age_seconds=snaps.SCORE_SNAPSHOT_MAX_AGE_SECONDS + 100)

    monkeypatch.setattr(
        snaps,
        "write_full_universe_snapshot",
        lambda progress_cb=None: {
            "ok": True,
            "count": 0,
            "written_at": "2026-08-21T00:00:00Z",
            "path": str(snap_path),
        },
    )

    snaps.stop_score_snapshot_scheduler()
    sched = snaps.ScoreSnapshotScheduler()
    sched.liveness.start()
    snaps._scheduler = sched

    try:
        out = snaps.revive_score_snapshot_scheduler()
        assert out["recycled"] is True
        assert out["revived"] is False
    finally:
        snaps.stop_score_snapshot_scheduler()


def test_try_revive_contract_uses_score_snapshot_revive():
    src = Path("internal/loop_stall_guard.py").read_text(encoding="utf-8")
    assert "from internal.council.score_snapshots import revive_score_snapshot_scheduler" in src
    assert "from internal.council.resolver_scheduler import revive_prediction_resolver_scheduler" in src
    assert "desk_snapshot_scheduler" not in src
    assert "start_pump_desk" not in src


def test_revive_recycled_on_started_with_degraded_status(tmp_path, monkeypatch):
    """Compatibility lock: started + degraded status still recycles (lifecycle branch).

    Parametrize statuses failing/stale/starved in-loop so the file stays at 13 pytest items.
    """
    for degraded in ("failing", "stale", "starved"):
        snap_path = _wire_snapshot_paths(tmp_path, monkeypatch)
        _make_stale_snapshot(snap_path)
        monkeypatch.setattr(
            snaps, "write_full_universe_snapshot", _fake_write_that_saves(snap_path)
        )

        snaps.stop_score_snapshot_scheduler()
        sched = snaps.ScoreSnapshotScheduler()
        sched.liveness.start()
        _seed_degraded_status(sched.liveness, degraded)
        assert sched.liveness.snapshot()["lifecycle"] == "started"
        snaps._scheduler = sched

        try:
            out = snaps.revive_score_snapshot_scheduler()
            assert out["recycled"] is True, degraded
        finally:
            snaps.stop_score_snapshot_scheduler()


def test_revive_false_on_new_lifecycle_with_degraded_status(tmp_path, monkeypatch):
    """lifecycle new must stay running=False even with a degraded status present."""
    snap_path = _wire_snapshot_paths(tmp_path, monkeypatch)
    _make_stale_snapshot(snap_path)
    monkeypatch.setattr(snaps, "write_full_universe_snapshot", _fake_write_that_saves(snap_path))

    snaps.stop_score_snapshot_scheduler()
    # Persist degraded status with lifecycle still "new", then hydrate a fresh tracker.
    soul = tmp_path / "soul_map.json"
    now = time.time()
    soul.write_text(
        json.dumps(
            {
                "liveness": {
                    "score_snapshot": {
                        "lifecycle": "new",
                        "last_success_epoch": now - 10_000,
                        "last_event_epoch": now,
                        "consecutive_failures": 1,
                        "consecutive_skips": 0,
                        "last_error": "boom",
                        "last_evidence": {"scanned": 1},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    sched = snaps.ScoreSnapshotScheduler()
    live = sched.liveness.snapshot()
    assert live["lifecycle"] == "new"
    assert live["status"] == "failing"
    # no start()
    snaps._scheduler = sched

    try:
        out = snaps.revive_score_snapshot_scheduler()
        assert out["recycled"] is False
    finally:
        snaps.stop_score_snapshot_scheduler()


def test_revive_recycled_on_stopped_lifecycle_with_degraded_status(tmp_path, monkeypatch):
    """ONLY proof status branch broadens running beyond lifecycle==started.

    Covers failing/stale/starved (parametrize-over-statuses). Prefer soul_map
    hydrate; fall back to tracker._lifecycle='stopped' when registry/cache is warm.
    """
    import internal.store.soul_map_io as smio

    for degraded in ("failing", "stale", "starved"):
        snap_path = _wire_snapshot_paths(tmp_path, monkeypatch)
        _make_stale_snapshot(snap_path)
        monkeypatch.setattr(
            snaps, "write_full_universe_snapshot", _fake_write_that_saves(snap_path)
        )

        snaps.stop_score_snapshot_scheduler()
        soul = tmp_path / "soul_map.json"
        now = time.time()
        base = {
            "lifecycle": "stopped",
            "last_success_epoch": now - 10_000,
            "last_event_epoch": now,
            "consecutive_failures": 0,
            "consecutive_skips": 0,
            "last_error": None,
            "last_evidence": {"scanned": 1},
        }
        soul.write_text(
            json.dumps({"liveness": {"score_snapshot": base}}), encoding="utf-8"
        )
        # Bypass TTL cache so hydrate sees the stopped bucket we just wrote.
        with smio._meta_lock:
            smio._cache.clear()

        sched = snaps.ScoreSnapshotScheduler()
        if sched.liveness.snapshot().get("lifecycle") != "stopped":
            # Fallback: direct lifecycle seed + degraded status.
            sched.liveness._lifecycle = "stopped"
        _seed_degraded_status(sched.liveness, degraded)
        sched.liveness._lifecycle = "stopped"
        live = sched.liveness.snapshot()
        assert live["lifecycle"] == "stopped", live
        assert live["status"] == degraded, live
        snaps._scheduler = sched

        try:
            out = snaps.revive_score_snapshot_scheduler()
            assert out["recycled"] is True, degraded
        finally:
            snaps.stop_score_snapshot_scheduler()


def _owner_env(monkeypatch, tmp_path):
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("WORKER_HEAVY", "essential")
    monkeypatch.delenv("STAGE2_HOP", raising=False)
    monkeypatch.delenv("SCORE_SNAPSHOT_SCHEDULER_ENABLED", raising=False)
    monkeypatch.setenv("SCORE_SNAPSHOT_CYCLE_PATH", str(tmp_path / "cycle.json"))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(tmp_path / "volume.json"))
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOT_SEED_PATH", str(tmp_path / "seed.json"))


def _write_young_snapshot(path) -> None:
    path.write_text(
        json.dumps(
            complete_snapshot_payload(
                day_rows=[{"netuid": 1, "total_score": 1.0}],
                written_at=snaps._now_iso(),
            )
        ),
        encoding="utf-8",
    )


def test_owner_without_receipt_is_not_kept_alive_by_a_young_seed(tmp_path, monkeypatch):
    """A seed is a static artifact: a young one must not hide a producer that never ran."""
    _owner_env(monkeypatch, tmp_path)
    _write_young_snapshot(tmp_path / "seed.json")
    assert snaps.read_served_snapshot().origin == "seed"
    age = loop_stall_guard._snapshot_age_seconds()
    assert age is not None
    assert age > MAX_SNAPSHOT_AGE_SECONDS


def test_owner_without_receipt_reads_a_young_volume_snapshot_as_young(tmp_path, monkeypatch):
    """Receipt write may have failed while the producer keeps publishing to the volume."""
    _owner_env(monkeypatch, tmp_path)
    _write_young_snapshot(tmp_path / "volume.json")
    assert snaps.read_served_snapshot().origin == "volume"
    age = loop_stall_guard._snapshot_age_seconds()
    assert age is not None
    assert age < MAX_SNAPSHOT_AGE_SECONDS


def test_owner_without_receipt_and_an_old_volume_snapshot_is_stale(tmp_path, monkeypatch):
    _owner_env(monkeypatch, tmp_path)
    _write_young_snapshot(tmp_path / "volume.json")
    old = time.time() - 10 * MAX_SNAPSHOT_AGE_SECONDS
    payload = json.loads((tmp_path / "volume.json").read_text(encoding="utf-8"))
    stamp = datetime.fromtimestamp(old, timezone.utc).isoformat()
    payload["written_at"] = payload["build_started_at"] = stamp
    (tmp_path / "volume.json").write_text(json.dumps(payload), encoding="utf-8")
    age = loop_stall_guard._snapshot_age_seconds()
    assert age is not None
    assert age > MAX_SNAPSHOT_AGE_SECONDS


def test_owner_with_servable_volume_snapshot_of_unknown_age_is_unknown_not_stale(
    tmp_path, monkeypatch
):
    """Readers still have a snapshot: an unknown age must not strike, revive or exit."""
    _owner_env(monkeypatch, tmp_path)
    _write_young_snapshot(tmp_path / "volume.json")
    served = snaps.ServedSnapshot(
        snaps.ServedState.AGED, {"day": {}}, None, "volume", None
    )
    monkeypatch.setattr(snaps, "read_served_snapshot", lambda *a, **k: served)
    assert loop_stall_guard._snapshot_age_seconds() is None


def _iso_offset(seconds: float) -> str:
    return datetime.fromtimestamp(time.time() + seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_receipt(tmp_path, seconds_from_now: float) -> None:
    (tmp_path / "cycle.json").write_text(
        json.dumps({"attempted_at": _iso_offset(seconds_from_now), "outcome": "published"}),
        encoding="utf-8",
    )


def _write_volume_dated(tmp_path, seconds_from_now: float) -> None:
    payload = complete_snapshot_payload(
        day_rows=[{"netuid": 1, "total_score": 1.0}], written_at=_iso_offset(seconds_from_now)
    )
    payload["build_started_at"] = payload["written_at"] = _iso_offset(seconds_from_now)
    (tmp_path / "volume.json").write_text(json.dumps(payload), encoding="utf-8")


def test_future_dated_receipt_is_stale_not_fresh_forever(tmp_path, monkeypatch):
    """A far-future receipt (clock step, corrupt file) cannot prove the producer is alive."""
    _owner_env(monkeypatch, tmp_path)
    _write_receipt(tmp_path, 30 * 86400)
    age = loop_stall_guard._snapshot_age_seconds()
    assert age is not None
    assert age > MAX_SNAPSHOT_AGE_SECONDS


def test_future_dated_volume_snapshot_without_receipt_is_stale(tmp_path, monkeypatch):
    _owner_env(monkeypatch, tmp_path)
    _write_volume_dated(tmp_path, 30 * 86400)
    assert snaps.read_served_snapshot().origin == "volume"
    age = loop_stall_guard._snapshot_age_seconds()
    assert age is not None
    assert age > MAX_SNAPSHOT_AGE_SECONDS


def test_small_clock_skew_still_reads_as_young(tmp_path, monkeypatch):
    _owner_env(monkeypatch, tmp_path)
    _write_receipt(tmp_path, 60)
    age = loop_stall_guard._snapshot_age_seconds()
    assert age is not None and age < MAX_SNAPSHOT_AGE_SECONDS
    (tmp_path / "cycle.json").unlink()
    _write_volume_dated(tmp_path, 60)
    age = loop_stall_guard._snapshot_age_seconds()
    assert age is not None and age < MAX_SNAPSHOT_AGE_SECONDS


def test_owner_with_no_snapshot_at_all_is_stale_on_first_check(tmp_path, monkeypatch):
    _owner_env(monkeypatch, tmp_path)
    age = loop_stall_guard._snapshot_age_seconds()
    assert age is not None
    assert age > MAX_SNAPSHOT_AGE_SECONDS


def test_owner_with_old_receipt_is_stale_even_when_the_volume_is_young(tmp_path, monkeypatch):
    _owner_env(monkeypatch, tmp_path)
    snaps.publish_complete_snapshot(
        complete_snapshot_payload(
            day_rows=[{"netuid": 1, "total_score": 1.0}],
            written_at=snaps._now_iso(),
        ),
        str(tmp_path / "volume.json"),
    )
    (tmp_path / "cycle.json").write_text(
        json.dumps({"attempted_at": "2020-01-01T00:00:00Z", "outcome": "published"}),
        encoding="utf-8",
    )
    age = loop_stall_guard._snapshot_age_seconds()
    assert age is not None
    assert age > MAX_SNAPSHOT_AGE_SECONDS


class _GuardExit(Exception):
    def __init__(self, code):
        self.code = code


class _GuardStop(Exception):
    pass


def _drive_guard(monkeypatch, *, ticks: int, age_probe=None):
    """Run the real guard loop for ``ticks`` checks; os._exit and sleep are stubbed.

    Returns (exit_code_or_None, revive_results).
    """
    results: list = []
    real_try_revive = loop_stall_guard._try_revive

    def _recording_revive():
        out = real_try_revive()
        results.append(out)
        return out

    state = {"n": 0}

    def _sleep(_s):
        state["n"] += 1
        if state["n"] > ticks:
            raise _GuardStop()

    def _exit(code):
        raise _GuardExit(code)

    monkeypatch.setattr(loop_stall_guard, "ENABLED", True)
    monkeypatch.setattr(loop_stall_guard, "KILL_ENABLED", True)
    monkeypatch.setattr(loop_stall_guard, "BOOT_GRACE_SECONDS", 0)
    monkeypatch.setattr(loop_stall_guard, "CONSECUTIVE_CHECKS", 3)
    monkeypatch.setattr(loop_stall_guard, "_try_revive", _recording_revive)
    monkeypatch.setattr(loop_stall_guard, "_resolver_tick_age_seconds", lambda: None)
    if age_probe is not None:
        monkeypatch.setattr(loop_stall_guard, "_snapshot_age_seconds", age_probe)
    monkeypatch.setattr(loop_stall_guard.time, "sleep", _sleep)
    monkeypatch.setattr(loop_stall_guard.os, "_exit", _exit)
    try:
        loop_stall_guard._guard_loop()
    except _GuardExit as exc:
        return exc.code, results
    except _GuardStop:
        return None, results
    return "returned_idle", results


@pytest.mark.parametrize(
    "env",
    [{"WORKER_HEAVY": "off"}, {"STAGE2_HOP": "1"}, {"SCORE_SNAPSHOT_SCHEDULER_ENABLED": "off"}],
    ids=["worker_heavy_off", "hop", "scheduler_off"],
)
def test_non_owner_with_a_stale_snapshot_never_revives_or_exits(tmp_path, monkeypatch, env):
    """Claude blocker: a non-owner worker with a stale file must be idle for any number of checks."""
    snap_path = _wire_snapshot_paths(tmp_path, monkeypatch)
    _make_stale_snapshot(snap_path)
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("WORKER_HEAVY", "essential")
    monkeypatch.delenv("STAGE2_HOP", raising=False)
    monkeypatch.delenv("SCORE_SNAPSHOT_SCHEDULER_ENABLED", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert loop_health._snapshot_age_seconds(str(snap_path)) > loop_stall_guard.MAX_SNAPSHOT_AGE_SECONDS
    code, revives = _drive_guard(monkeypatch, ticks=20)
    assert code in (None, "returned_idle")
    assert revives == []


def test_owner_with_a_stale_snapshot_still_strikes_and_exits(tmp_path, monkeypatch):
    """Control: the owner keeps the existing wedge behaviour (revive that does nothing, then exit)."""
    snap_path = _wire_snapshot_paths(tmp_path, monkeypatch)
    _make_stale_snapshot(snap_path)
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("WORKER_HEAVY", "essential")
    monkeypatch.delenv("STAGE2_HOP", raising=False)
    monkeypatch.delenv("SCORE_SNAPSHOT_SCHEDULER_ENABLED", raising=False)
    monkeypatch.setattr(snaps, "write_full_universe_snapshot", lambda progress_cb=None: {"ok": False})
    code, revives = _drive_guard(monkeypatch, ticks=20)
    assert code == 1
    assert len(revives) == 1


def test_not_owner_revive_result_is_idle_not_a_strike(tmp_path, monkeypatch):
    """Even if the age probe wrongly reports stale, a not_owner revive keeps the guard idle."""
    snap_path = _wire_snapshot_paths(tmp_path, monkeypatch)
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.setenv("WORKER_HEAVY", "off")
    monkeypatch.delenv("STAGE2_HOP", raising=False)
    monkeypatch.delenv("SCORE_SNAPSHOT_SCHEDULER_ENABLED", raising=False)
    code, revives = _drive_guard(
        monkeypatch, ticks=20, age_probe=lambda: float(loop_stall_guard.MAX_SNAPSHOT_AGE_SECONDS + 1)
    )
    assert code in (None, "returned_idle")
    assert revives and all(r.get("reason") == "not_owner" for r in revives)
