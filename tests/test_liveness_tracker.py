"""Self-tests for the LivenessTracker contract itself."""

import json

import pytest

from internal.liveness import LivenessTracker
from liveness_conformance import assert_liveness_compliant, make_tracker_factory


def test_contract():
    assert_liveness_compliant(make_tracker_factory())


def test_skip_burst_with_fresh_success_is_ok():
    """The false-positive guard: a healthy scheduler losing the heavy-job
    gate repeatedly must NOT flip to starved while its success is fresh."""
    t = LivenessTracker("bursty", interval_seconds=60, persist=False, skip_limit=2)
    t.record_success(evidence={"rows_resolved": 5})
    for _ in range(10):
        t.record_skip("heavy_job_busy")
    snap = t.snapshot()
    assert snap["status"] == "ok", snap


def test_starved_requires_stale_success():
    t = LivenessTracker("starvy", interval_seconds=60, persist=False, skip_limit=2)
    t.record_success(evidence={"scanned": 1})
    # white-box: force success age past the stale window
    t._last_success_epoch -= 600
    t.record_skip("heavy_job_busy")
    t.record_skip("heavy_job_busy")
    snap = t.snapshot()
    assert snap["status"] == "starved", snap


def test_stale_auto_degrades():
    t = LivenessTracker("staley", interval_seconds=60, persist=False)
    t.record_success(evidence={"scanned": 1})
    t._last_success_epoch -= 600  # > interval * staleness_factor(2)
    assert t.snapshot()["status"] == "stale"


def test_no_success_is_never_ok():
    t = LivenessTracker("freshy", interval_seconds=60, persist=False)
    t.start()
    snap = t.snapshot()
    assert snap["lifecycle"] == "started"
    assert snap["status"] == "no_success_yet"


def test_known_intervals_include_pump_desk_snapshot(monkeypatch):
    monkeypatch.setenv("PUMP_DESK_SNAPSHOT_MINUTES", "20")

    from internal.liveness import _known_tracker_intervals

    assert _known_tracker_intervals()["pump_desk_snapshot"] == 20 * 60


def test_empty_evidence_raises():
    t = LivenessTracker("evict", interval_seconds=60, persist=False)
    with pytest.raises(ValueError):
        t.record_success(evidence={})
    with pytest.raises(ValueError):
        t.record_success()


def test_persistence_round_trip_real_soul_map(tmp_path, monkeypatch):
    """END-TO-END honesty of the restart story: write through the REAL
    soul_map_io machinery to a real file on disk, then construct a fresh
    tracker and prove it boots from persisted truth instead of inventing
    null/stopped. This is the spec's cross-process-persistence requirement."""
    import internal.store.soul_map_io as smio

    target = tmp_path / "data" / "soul_map.json"
    monkeypatch.setattr(smio, "_resolve_path", lambda path=None: str(target))

    from internal.liveness import LivenessTracker as LT

    t1 = LT("persist-e2e", interval_seconds=60, persist=True)
    t1.start()
    t1.record_success(evidence={"rows_resolved": 3})

    # the file must actually exist with our state in it
    assert target.exists(), "soul_map was never written to disk"
    blob = json.loads(target.read_text())
    assert "liveness" in blob and "persist-e2e" in blob["liveness"]
    stored = blob["liveness"]["persist-e2e"]
    assert isinstance(stored.get("last_success_epoch"), float)

    # fresh process simulation: brand-new instance reads persisted truth
    t2 = LT("persist-e2e", interval_seconds=60, persist=True)
    snap = t2.snapshot()
    assert snap["source"] == "persisted", snap
    assert snap["last_success_at"] is not None
    assert snap["status"] == "ok", snap
