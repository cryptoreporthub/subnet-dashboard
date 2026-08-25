"""Loop stall guard — probe/revive must target score_snapshots.json producer."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from internal.council import score_snapshots as snaps
from internal.learning import loop_health
from internal import loop_stall_guard
from internal.loop_stall_guard import (
    MAX_SNAPSHOT_AGE_SECONDS,
    _next_resolver_stale_strikes,
    _try_revive,
)


def _make_stale_snapshot(path, *, age_seconds: float = 100_000) -> None:
    path.write_text('{"day":[],"hour":[]}', encoding="utf-8")
    old = time.time() - age_seconds
    os.utime(path, (old, old))


def _wire_snapshot_paths(tmp_path, monkeypatch):
    snap_path = tmp_path / "score_snapshots.json"
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(snap_path))
    monkeypatch.setenv("SCORE_SNAPSHOTS_PATH", str(snap_path))
    monkeypatch.setattr(loop_health, "SCORE_SNAPSHOTS_PATH", str(snap_path))
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    return snap_path


def _fake_write_that_saves(snap_path):
    def _fake_write(progress_cb=None):
        if progress_cb:
            progress_cb(1, 1)
        snaps.save_score_snapshot(
            {
                "day": [{"netuid": 1, "total_score": 1.0}],
                "hour": [],
                "written_at": "2026-08-21T00:00:00Z",
            },
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

    # Simulate alive-but-hung: scheduler claims running but file never updates.
    snaps.stop_score_snapshot_scheduler()
    sched = snaps.ScoreSnapshotScheduler()
    sched._running = True
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
    """5400–7200s window: guard already stale; recycle whenever _running."""
    snap_path = _wire_snapshot_paths(tmp_path, monkeypatch)
    guard_stale_age = MAX_SNAPSHOT_AGE_SECONDS + 100
    assert guard_stale_age < snaps.SCORE_SNAPSHOT_MAX_AGE_SECONDS
    _make_stale_snapshot(snap_path, age_seconds=guard_stale_age)
    monkeypatch.setattr(snaps, "write_full_universe_snapshot", _fake_write_that_saves(snap_path))

    snaps.stop_score_snapshot_scheduler()
    sched = snaps.ScoreSnapshotScheduler()
    sched._running = True
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
    sched._running = True
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
    sched._running = True
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
    """Young mtime + ok tick without save_score_snapshot must not claim revived."""
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
    """ok:True without save_score_snapshot must not count as revived."""
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
    sched._running = True
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
    assert "desk_snapshot_scheduler" not in src
    assert "start_pump_desk" not in src


def test_resolver_stall_restart_request_is_observable(monkeypatch, caplog):
    exits = []
    monkeypatch.setattr(loop_stall_guard, "KILL_ENABLED", True)
    monkeypatch.setattr(loop_stall_guard.os, "_exit", lambda code: exits.append(code))

    loop_stall_guard._request_supervisor_restart(
        signal="resolver tick",
        age_seconds=21_601,
        threshold_seconds=21_600,
        strikes=2,
    )

    assert exits == [1]
    assert "resolver tick stale for 2 checks" in caplog.text


def test_missing_resolver_tick_counts_toward_recovery(caplog):
    strikes = _next_resolver_stale_strikes(None, 0)

    assert strikes == 1
    assert "resolver tick missing" in caplog.text


def test_guard_restarts_after_boot_grace_for_missing_resolver_tick(monkeypatch):
    monotonic_values = iter((0.0, 100.0, 201.0, 202.0))
    sleep_calls = {"count": 0}
    restart_requests = []

    def _sleep(_seconds):
        sleep_calls["count"] += 1
        if sleep_calls["count"] > 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(loop_stall_guard, "_worker_mode", lambda: True)
    monkeypatch.setattr(loop_stall_guard, "BOOT_GRACE_SECONDS", 200)
    monkeypatch.setattr(loop_stall_guard, "CONSECUTIVE_CHECKS", 2)
    monkeypatch.setattr(loop_stall_guard, "_resolver_tick_age_seconds", lambda: None)
    monkeypatch.setattr(loop_stall_guard, "_snapshot_age_seconds", lambda: None)
    monkeypatch.setattr(loop_stall_guard.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(loop_stall_guard.time, "sleep", _sleep)
    monkeypatch.setattr(
        loop_stall_guard,
        "_request_supervisor_restart",
        lambda **kwargs: restart_requests.append(kwargs),
    )

    with pytest.raises(KeyboardInterrupt):
        loop_stall_guard._guard_loop()

    assert restart_requests == [
        {
            "signal": "resolver tick",
            "age_seconds": None,
            "threshold_seconds": loop_stall_guard.MAX_RESOLVER_AGE_SECONDS,
            "strikes": 2,
        }
    ]
