"""Integration — score snapshot write path emits Phase 1 coverage."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from internal.council import score_snapshots as snaps
from internal.council import snapshot_coverage as cov
from internal.subnet_universe import UniverseSnapshot, _validity_entry


@pytest.fixture(autouse=True)
def _reset_phase1_state():
    cov.reset_phase1_cycle_state_for_tests()
    yield
    cov.reset_phase1_cycle_state_for_tests()


def _ok_membership_snapshot() -> UniverseSnapshot:
    resolved = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return UniverseSnapshot(
        netuids=(1, 2),
        rows=({"netuid": 1, "name": "A"}, {"netuid": 2, "name": "B"}),
        resolved_at=resolved,
        status="ok",
        degraded=False,
        validity_map={
            "1": _validity_entry(validity="positive", sources=["taomarketcap"]),
            "2": _validity_entry(validity="positive", sources=["taomarketcap"]),
        },
    )


def test_write_emits_publish_wall_seconds_and_coverage(tmp_path, monkeypatch):
    path = tmp_path / "score_snapshots.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    monkeypatch.setenv("SCORE_SNAPSHOT_REGISTRY_ONLY", "on")
    monkeypatch.setattr(
        "internal.subnet_universe.get_snapshot",
        lambda: _ok_membership_snapshot(),
    )

    def _day(sn, _ctx):
        return {"total_score": float(sn["netuid"])}

    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_day", _day)
    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_hour", _day)
    monkeypatch.setattr(snaps, "_score_hour_enabled", lambda: False)
    hydrate = [{"netuid": 1, "name": "A"}, {"netuid": 2, "name": "B"}]
    monkeypatch.setattr("server._get_subnets_hydrate", lambda: (hydrate, "registry-fallback"))

    out = snaps.write_full_universe_snapshot()
    assert out.get("published") is True
    assert out.get("ok") is True
    coverage = out.get("coverage") or {}
    timing = coverage.get("timing") or {}
    assert timing.get("build_wall_seconds") is not None
    assert timing.get("publish_wall_seconds") is not None
    assert coverage.get("hour", {}).get("hour_copied_from_day") is True
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "coverage" in saved
    on_disk_timing = (saved.get("coverage") or {}).get("timing") or {}
    assert on_disk_timing.get("publish_wall_seconds") is not None
    assert cov.last_coverage_snapshot().get("complete") is True


def test_skipped_older_publish_sets_ok_false(tmp_path, monkeypatch):
    path = tmp_path / "score_snapshots.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    snaps.save_score_snapshot(
        {
            "build_started_at": "2026-09-22T12:00:00Z",
            "written_at": "2026-09-22T12:05:00Z",
            "day": [{"netuid": 2, "total_score": 2.0}],
            "hour": [],
        },
        str(path),
    )
    result = snaps.save_score_snapshot(
        {
            "build_started_at": "2026-09-22T11:00:00Z",
            "written_at": "2026-09-22T12:10:00Z",
            "day": [{"netuid": 1, "total_score": 1.0}],
            "hour": [],
            "coverage": {"complete": True},
        },
        str(path),
    )
    assert result.get("published") is False
    assert result.get("timing", {}).get("publish_wall_seconds") is not None


def test_metrics_registry_exposes_coverage_gauges():
    from internal.metrics import (
        SCORE_SNAPSHOT_COVERAGE_COMPLETE,
        SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS,
    )

    assert SCORE_SNAPSHOT_COVERAGE_COMPLETE._name.startswith("subnet_score_snapshot")
    assert SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS._name.endswith("publish_wall_seconds")
