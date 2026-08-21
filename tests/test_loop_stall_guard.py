"""Loop stall guard — probe/revive must target score_snapshots.json producer."""

from __future__ import annotations

import os
import time

from internal.council import score_snapshots as snaps
from internal.learning import loop_health
from internal.loop_stall_guard import _try_revive


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


def test_revive_resets_stale_snapshot_age(tmp_path, monkeypatch):
    snap_path = _wire_snapshot_paths(tmp_path, monkeypatch)
    _make_stale_snapshot(snap_path)

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

    monkeypatch.setattr(snaps, "write_full_universe_snapshot", _fake_write)

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

    def _fake_write(progress_cb=None):
        snaps.save_score_snapshot(
            {
                "day": [{"netuid": 7, "total_score": 7.0}],
                "hour": [],
                "written_at": "2026-08-21T00:00:00Z",
            },
            str(snap_path),
        )
        return {"ok": True, "count": 1, "path": str(snap_path)}

    monkeypatch.setattr(snaps, "write_full_universe_snapshot", _fake_write)

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
    finally:
        snaps.stop_score_snapshot_scheduler()


def test_revive_recycles_very_stale_running_scheduler(tmp_path, monkeypatch):
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
        assert out["revived"] is True
    finally:
        snaps.stop_score_snapshot_scheduler()
