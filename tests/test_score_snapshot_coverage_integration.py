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
    hour_block = coverage.get("hour") or {}
    assert hour_block.get("hour_copied_from_day") is True
    assert hour_block.get("status") == "copied"
    assert hour_block.get("attempted") == 0
    assert coverage.get("complete") is True
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "coverage" in saved
    on_disk_timing = (saved.get("coverage") or {}).get("timing") or {}
    assert on_disk_timing.get("build_wall_seconds") is not None
    assert "publish_wall_seconds" not in on_disk_timing
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


def test_metrics_endpoint_shows_coverage_after_disk_snapshot(tmp_path, monkeypatch):
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

    worker = __import__("multiprocessing").get_context("spawn").Process(
        target=snaps.write_full_universe_snapshot,
    )
    worker.start()
    worker.join(30)
    assert worker.exitcode == 0

    from fastapi.testclient import TestClient

    from server import app

    body = TestClient(app).get("/metrics").text
    assert "subnet_score_snapshot_coverage_complete" in body
    assert "subnet_score_snapshot_coverage_published" in body


def test_integration_feed_only_extra_not_scored(tmp_path, monkeypatch):
    """Deregistered/extra feed rows outside membership must not enter the scoring loop."""
    path = tmp_path / "score_snapshots.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    monkeypatch.setenv("SCORE_SNAPSHOT_REGISTRY_ONLY", "on")
    snap = UniverseSnapshot(
        netuids=(1, 2),
        rows=({"netuid": 1, "name": "A"}, {"netuid": 2, "name": "B"}),
        resolved_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        status="ok",
        degraded=False,
        validity_map={
            "1": _validity_entry(validity="positive", sources=["taomarketcap"]),
            "2": _validity_entry(validity="positive", sources=["taomarketcap"]),
        },
    )
    monkeypatch.setattr("internal.subnet_universe.get_snapshot", lambda: snap)
    attempted: list[int] = []

    def _day(sn, _ctx):
        attempted.append(int(sn["netuid"]))
        return {"total_score": float(sn["netuid"])}

    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_day", _day)
    monkeypatch.setattr(snaps, "_score_hour_enabled", lambda: False)
    hydrate = [
        {"netuid": 1, "name": "A"},
        {"netuid": 2, "name": "B"},
        {"netuid": 77, "name": "Feed-only"},
    ]
    monkeypatch.setattr("server._get_subnets_hydrate", lambda: (hydrate, "registry-fallback"))

    out = snaps.write_full_universe_snapshot()
    assert sorted(attempted) == [1, 2]
    timing = (out.get("coverage") or {}).get("timing") or {}
    assert timing.get("candidate_prep_seconds") is not None
    assert timing.get("excluded_feed_only_count") == 1


def test_metrics_green_to_stale_resets_gauges(tmp_path, monkeypatch):
    from datetime import timedelta

    from internal.metrics import SCORE_SNAPSHOT_COVERAGE_COMPLETE, refresh_from_state

    path = tmp_path / "score_snapshots.json"
    fresh = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    path.write_text(
        json.dumps(
            {
                "written_at": fresh,
                "build_started_at": fresh,
                "day": [{"netuid": 1, "total_score": 1.0}],
                "hour": [],
                "coverage": {"complete": True, "published": True, "day": {"succeeded": [1]}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    refresh_from_state()
    assert SCORE_SNAPSHOT_COVERAGE_COMPLETE._value.get() == 1.0

    old = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat().replace("+00:00", "Z")
    path.write_text(
        json.dumps(
            {
                "written_at": old,
                "build_started_at": old,
                "day": [],
                "hour": [],
                "coverage": {"complete": True, "published": True},
            }
        ),
        encoding="utf-8",
    )
    refresh_from_state()
    assert SCORE_SNAPSHOT_COVERAGE_COMPLETE._value.get() == 0.0


def test_metrics_green_to_missing_disk_resets_gauges(tmp_path, monkeypatch):
    from internal.metrics import (
        SCORE_SNAPSHOT_AGE_SECONDS,
        SCORE_SNAPSHOT_AGE_UNAVAILABLE,
        SCORE_SNAPSHOT_COVERAGE_COMPLETE,
        refresh_from_state,
    )

    path = tmp_path / "score_snapshots.json"
    fresh = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    path.write_text(
        json.dumps(
            {
                "written_at": fresh,
                "build_started_at": fresh,
                "day": [],
                "hour": [],
                "coverage": {"complete": True, "published": True},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    refresh_from_state()
    assert SCORE_SNAPSHOT_COVERAGE_COMPLETE._value.get() == 1.0
    fresh_age = SCORE_SNAPSHOT_AGE_SECONDS._value.get()
    assert fresh_age is not None and fresh_age >= 0.0
    path.unlink()
    refresh_from_state()
    assert SCORE_SNAPSHOT_COVERAGE_COMPLETE._value.get() == 0.0
    assert SCORE_SNAPSHOT_AGE_SECONDS._value.get() == SCORE_SNAPSHOT_AGE_UNAVAILABLE
    assert SCORE_SNAPSHOT_AGE_SECONDS._value.get() != fresh_age


def test_metrics_stale_in_process_reads_fresher_disk(tmp_path, monkeypatch):
    from internal.metrics import SCORE_SNAPSHOT_COVERAGE_COMPLETE, refresh_from_state

    path = tmp_path / "score_snapshots.json"
    fresh = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    path.write_text(
        json.dumps(
            {
                "written_at": fresh,
                "build_started_at": fresh,
                "day": [{"netuid": 1, "total_score": 1.0}],
                "hour": [],
                "coverage": {
                    "complete": True,
                    "published": True,
                    "day": {"succeeded": [1]},
                    "hour": {"succeeded": [1]},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    cov.note_cycle({"complete": False, "published": False})
    refresh_from_state()
    assert SCORE_SNAPSHOT_COVERAGE_COMPLETE._value.get() == 1.0


def test_scoring_exception_counts_as_attempted(tmp_path, monkeypatch):
    path = tmp_path / "score_snapshots.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    monkeypatch.setenv("SCORE_SNAPSHOT_REGISTRY_ONLY", "on")
    monkeypatch.setattr(
        "internal.subnet_universe.get_snapshot",
        lambda: _ok_membership_snapshot(),
    )

    def _day(sn, _ctx):
        if int(sn["netuid"]) == 2:
            raise RuntimeError("boom")
        return {"total_score": float(sn["netuid"])}

    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_day", _day)
    monkeypatch.setattr(snaps, "_score_hour_enabled", lambda: False)
    hydrate = [{"netuid": 1, "name": "A"}, {"netuid": 2, "name": "B"}]
    monkeypatch.setattr("server._get_subnets_hydrate", lambda: (hydrate, "registry-fallback"))

    out = snaps.write_full_universe_snapshot()
    day = (out.get("coverage") or {}).get("day") or {}
    assert day.get("attempted") == 2
    assert out.get("complete") is False


def test_capture_budget_includes_hydration_delay(tmp_path, monkeypatch):
    import time as _time

    path = tmp_path / "score_snapshots.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    monkeypatch.setenv("SCORE_SNAPSHOT_REGISTRY_ONLY", "on")
    monkeypatch.setattr(cov, "PHASE1_COVERAGE_CAPTURE_MAX_SECONDS", 1)

    def _slow_hydrate():
        _time.sleep(1.2)
        return ([{"netuid": 1, "name": "A"}], "registry-fallback")

    monkeypatch.setattr("server._get_subnets_hydrate", _slow_hydrate)
    monkeypatch.setattr(
        "internal.subnet_universe.get_snapshot",
        lambda: _ok_membership_snapshot(),
    )
    monkeypatch.setattr(
        "internal.council.state_vector.score_subnet_for_day",
        lambda sn, _ctx: {"total_score": 1.0},
    )
    monkeypatch.setattr(snaps, "_score_hour_enabled", lambda: False)

    out = snaps.write_full_universe_snapshot()
    coverage = out.get("coverage") or {}
    assert coverage.get("complete") is False
    assert coverage.get("capture_reason") == "capture_timeout"


def test_stale_scrape_resets_coverage_but_keeps_process_publish_wall(tmp_path, monkeypatch):
    from datetime import timedelta

    from internal.metrics import (
        SCORE_SNAPSHOT_COVERAGE_COMPLETE,
        SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS,
        refresh_from_state,
    )

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

    snaps.write_full_universe_snapshot()
    publish_before = SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS._value.get()
    assert publish_before > 0
    old = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat().replace("+00:00", "Z")
    path.write_text(
        json.dumps(
            {
                "written_at": old,
                "build_started_at": old,
                "day": [],
                "hour": [],
                "coverage": {"complete": True, "published": True},
            }
        ),
        encoding="utf-8",
    )
    refresh_from_state()
    assert SCORE_SNAPSHOT_COVERAGE_COMPLETE._value.get() == 0.0
    assert SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS._value.get() == publish_before


def test_metrics_skips_stale_disk_coverage(tmp_path, monkeypatch):
    from datetime import timedelta

    from internal.metrics import SCORE_SNAPSHOT_COVERAGE_COMPLETE, refresh_from_state

    path = tmp_path / "score_snapshots.json"
    old = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat().replace("+00:00", "Z")
    path.write_text(
        json.dumps(
            {
                "written_at": old,
                "build_started_at": old,
                "day": [],
                "hour": [],
                "coverage": {"complete": True, "published": True},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    cov.reset_phase1_cycle_state_for_tests()
    SCORE_SNAPSHOT_COVERAGE_COMPLETE.set(0.0)
    refresh_from_state()
    assert SCORE_SNAPSHOT_COVERAGE_COMPLETE._value.get() == 0.0


def test_scrape_reads_previous_publish_from_snapshot_not_soul_map(tmp_path, monkeypatch):
    from internal.metrics import (
        SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS,
        refresh_from_state,
    )

    def _forbid_soul_map(*_args, **_kwargs):
        raise AssertionError("soul_map read on metrics scrape")

    monkeypatch.setattr("internal.council.weights._load_raw", _forbid_soul_map)
    path = tmp_path / "score_snapshots.json"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    path.write_text(
        json.dumps(
            {
                "written_at": now,
                "build_started_at": now,
                "day": [{"netuid": 1, "total_score": 1.0}],
                "hour": [],
                "coverage": {
                    "published": True,
                    "complete": False,
                    "timing": {
                        "build_wall_seconds": 1.0,
                        "previous_publish_wall_seconds": 0.015,
                    },
                    "day": {"succeeded": [1], "complete": False},
                    "hour": {"succeeded": [], "complete": False},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    cov.reset_phase1_cycle_state_for_tests()
    refresh_from_state()
    assert SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS._value.get() == 0.015


def test_second_write_persists_previous_publish_one_cycle_behind(tmp_path, monkeypatch):
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

    first = snaps.write_full_universe_snapshot()
    first_pub = (first.get("coverage") or {}).get("timing", {}).get("publish_wall_seconds")
    assert first_pub is not None
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "previous_publish_wall_seconds" not in (
        (saved.get("coverage") or {}).get("timing") or {}
    )
    second = snaps.write_full_universe_snapshot()
    saved2 = json.loads(path.read_text(encoding="utf-8"))
    on_disk_prev = (saved2.get("coverage") or {}).get("timing", {}).get(
        "previous_publish_wall_seconds"
    )
    assert on_disk_prev == round(float(first_pub), 6)
    second_pub = (second.get("coverage") or {}).get("timing", {}).get("publish_wall_seconds")
    assert second_pub is not None


def test_fresh_process_publish_wall_unavailable(tmp_path, monkeypatch):
    from internal.metrics import (
        SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS,
        SCORE_SNAPSHOT_TIMING_PUBLISH_UNAVAILABLE,
        refresh_from_state,
    )

    path = tmp_path / "score_snapshots.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    cov.reset_phase1_cycle_state_for_tests()
    refresh_from_state()
    assert (
        SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS._value.get()
        == SCORE_SNAPSHOT_TIMING_PUBLISH_UNAVAILABLE
    )


def test_hour_copied_horizon_gauges_on_scrape(tmp_path, monkeypatch):
    from internal.metrics import (
        SCORE_SNAPSHOT_HORIZON_COPIED,
        SCORE_SNAPSHOT_HORIZON_SUCCEEDED,
        refresh_from_state,
    )

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

    snaps.write_full_universe_snapshot()
    refresh_from_state()
    assert SCORE_SNAPSHOT_HORIZON_SUCCEEDED.labels(horizon="hour")._value.get() == 0.0
    assert SCORE_SNAPSHOT_HORIZON_COPIED.labels(horizon="hour")._value.get() == 2.0
    assert SCORE_SNAPSHOT_HORIZON_SUCCEEDED.labels(horizon="day")._value.get() == 2.0


def test_legacy_disk_hour_without_status_infers_copied_on_scrape(tmp_path, monkeypatch):
    from internal.metrics import (
        SCORE_SNAPSHOT_HORIZON_COPIED,
        SCORE_SNAPSHOT_HORIZON_SUCCEEDED,
        refresh_from_state,
    )

    path = tmp_path / "score_snapshots.json"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    path.write_text(
        json.dumps(
            {
                "written_at": now,
                "build_started_at": now,
                "day": [{"netuid": 1, "total_score": 1.0}, {"netuid": 2, "total_score": 2.0}],
                "hour": [],
                "coverage": {
                    "published": True,
                    "complete": True,
                    "timing": {"build_wall_seconds": 1.0},
                    "day": {
                        "succeeded": [1, 2],
                        "complete": True,
                    },
                    "hour": {
                        "succeeded": [1, 2],
                        "hour_copied_from_day": True,
                        "attempted": 0,
                        "complete": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    cov.reset_phase1_cycle_state_for_tests()
    refresh_from_state()
    assert SCORE_SNAPSHOT_HORIZON_SUCCEEDED.labels(horizon="hour")._value.get() == 0.0
    assert SCORE_SNAPSHOT_HORIZON_COPIED.labels(horizon="hour")._value.get() == 2.0


def test_metrics_publish_wall_unavailable_from_disk_coverage(tmp_path, monkeypatch):
    from internal.metrics import (
        SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS,
        SCORE_SNAPSHOT_TIMING_PUBLISH_UNAVAILABLE,
        refresh_from_state,
    )

    path = tmp_path / "score_snapshots.json"
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    path.write_text(
        json.dumps(
            {
                "written_at": now,
                "build_started_at": now,
                "day": [{"netuid": 1, "total_score": 1.0}],
                "hour": [],
                "coverage": {
                    "published": True,
                    "complete": False,
                    "timing": {"build_wall_seconds": 1.0},
                    "day": {"succeeded": [1], "complete": False},
                    "hour": {"succeeded": [], "complete": False},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    cov.reset_phase1_cycle_state_for_tests()
    SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS.set(0.5)
    refresh_from_state()
    assert (
        SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS._value.get()
        == SCORE_SNAPSHOT_TIMING_PUBLISH_UNAVAILABLE
    )


def test_metrics_registry_exposes_coverage_gauges():
    from internal.metrics import (
        SCORE_SNAPSHOT_COVERAGE_COMPLETE,
        SCORE_SNAPSHOT_HORIZON_COPIED,
        SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS,
    )

    assert SCORE_SNAPSHOT_COVERAGE_COMPLETE._name.startswith("subnet_score_snapshot")
    assert SCORE_SNAPSHOT_TIMING_PUBLISH_SECONDS._name.endswith("publish_wall_seconds")
    assert SCORE_SNAPSHOT_HORIZON_COPIED._name.endswith("horizon_copied")
