"""MC MODIFY items — liveness on published, capture timeout, soul_map slim coverage."""

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


def _ok_membership_snapshot(**overrides) -> UniverseSnapshot:
    resolved = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    base = {
        "netuids": (1, 2),
        "rows": ({"netuid": 1, "name": "A"}, {"netuid": 2, "name": "B"}),
        "resolved_at": resolved,
        "status": "ok",
        "degraded": False,
        "cap_reached": True,
        "refresh_incomplete": True,
        "validity_map": {
            "1": _validity_entry(validity="positive", sources=["taomarketcap"]),
            "2": _validity_entry(validity="positive", sources=["taomarketcap"]),
        },
    }
    base.update(overrides)
    return UniverseSnapshot(**base)


def _wire_minimal_write(monkeypatch, tmp_path, membership: UniverseSnapshot):
    path = tmp_path / "score_snapshots.json"
    monkeypatch.setattr(snaps, "SCORE_SNAPSHOTS_PATH", str(path))
    monkeypatch.setenv("SCORE_SNAPSHOT_REGISTRY_ONLY", "on")
    monkeypatch.setattr("internal.subnet_universe.get_snapshot", lambda: membership)

    def _day(sn, _ctx):
        return {"total_score": float(sn["netuid"])}

    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_day", _day)
    monkeypatch.setattr("internal.council.state_vector.score_subnet_for_hour", _day)
    monkeypatch.setattr(snaps, "_score_hour_enabled", lambda: False)
    hydrate = [{"netuid": 1, "name": "A"}, {"netuid": 2, "name": "B"}]
    monkeypatch.setattr("server._get_subnets_hydrate", lambda: (hydrate, "registry-fallback"))
    return path


def test_liveness_success_when_published_incomplete(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    _wire_minimal_write(monkeypatch, tmp_path, _ok_membership_snapshot())

    sched = snaps.ScoreSnapshotScheduler()
    sched._scoring_in_progress = lambda: False
    out = sched._tick(reschedule=False)
    assert out.get("published") is True
    assert out.get("complete") is False
    snap = sched.liveness.snapshot()
    assert snap["status"] == "ok"
    evidence = snap.get("last_evidence") or {}
    assert evidence.get("coverage", {}).get("complete") is False


def test_capture_timeout_still_publishes(tmp_path, monkeypatch):
    path = _wire_minimal_write(monkeypatch, tmp_path, _ok_membership_snapshot())
    monkeypatch.setattr(cov, "coverage_capture_deadline_seconds", lambda _start: False)

    out = snaps.write_full_universe_snapshot()
    assert out.get("published") is True
    assert out.get("complete") is False
    assert (out.get("coverage") or {}).get("capture_reason") == "capture_timeout"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved.get("coverage", {}).get("capture_reason") == "capture_timeout"


def test_skipped_older_records_liveness_skip(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    sched = snaps.ScoreSnapshotScheduler()
    sched._record_liveness({"published": False, "skipped_older": True})
    assert sched.liveness.snapshot()["last_skip_reason"] == "skipped_older"


def test_on_disk_coverage_timing_is_build_only_ac9a(tmp_path, monkeypatch):
    """AC #9a: publish_wall_seconds is not persisted in score_snapshots.json."""
    path = _wire_minimal_write(monkeypatch, tmp_path, _ok_membership_snapshot())
    out = snaps.write_full_universe_snapshot()
    timing = (out.get("coverage") or {}).get("timing") or {}
    assert timing.get("publish_wall_seconds") is not None
    saved = json.loads(path.read_text(encoding="utf-8"))
    on_disk_timing = (saved.get("coverage") or {}).get("timing") or {}
    assert on_disk_timing.get("build_wall_seconds") is not None
    assert "publish_wall_seconds" not in on_disk_timing


def test_one_locked_replace_per_publish_cycle(tmp_path, monkeypatch):
    path = _wire_minimal_write(monkeypatch, tmp_path, _ok_membership_snapshot())
    snap_path = str(path)
    replace_calls: list[str] = []
    real_replace = __import__("os").replace

    def _spy_replace(src, dst, *args, **kwargs):
        if dst == snap_path:
            replace_calls.append(dst)
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr("os.replace", _spy_replace)
    snaps.write_full_universe_snapshot()
    assert replace_calls == [snap_path]


def test_persist_cycle_summary_coverage_is_counts_only(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    sched = snaps.ScoreSnapshotScheduler()
    sched._persist_cycle_summary(
        {
            "run_at": "2026-07-26T12:00:00Z",
            "ok": True,
            "published": True,
            "complete": False,
            "coverage": {
                "published": True,
                "complete": False,
                "day": {
                    "expected": [1, 2, 3],
                    "succeeded": [1, 2],
                    "failed": [{"netuid": 3}],
                    "attempted": 3,
                    "complete": False,
                },
                "hour": {
                    "succeeded": [1, 2],
                    "failed": [],
                    "attempted": 3,
                    "complete": False,
                    "hour_copied_from_day": True,
                },
                "membership": {"fresh": True, "expected_netuids": [1, 2, 3]},
                "timing": {"build_wall_seconds": 1.0, "publish_wall_seconds": 0.01},
            },
        }
    )
    data = json.loads(soul.read_text(encoding="utf-8"))
    slim = data["score_snapshot_scheduler"]["last_cycle"]["coverage"]
    assert "expected" not in (slim.get("day") or {})
    assert slim["day"]["succeeded_count"] == 2
    assert slim["day"]["failed_count"] == 1
    assert "expected_netuids" not in (slim.get("membership") or {})
