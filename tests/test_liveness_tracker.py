"""Self-tests for the LivenessTracker contract itself."""

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


def test_empty_evidence_raises():
    t = LivenessTracker("evict", interval_seconds=60, persist=False)
    with pytest.raises(ValueError):
        t.record_success(evidence={})
    with pytest.raises(ValueError):
        t.record_success()
