"""Shared conformance fixture for LivenessTracker adoption.

Every migrated scheduler MUST run assert_liveness_compliant over a factory
that returns its tracker. This makes correct usage the path of least
resistance; the AST guard (test_no_handrolled_liveness.py) makes lying hard.
"""

import time

import pytest

from internal.liveness import LivenessTracker


def assert_liveness_compliant(make_tracker):
    """Contract checks every adopted tracker must satisfy."""
    t = make_tracker()

    # 1. a fresh tracker must never report ok
    snap = t.snapshot()
    assert snap["status"] != "ok", "fresh tracker reported ok"

    # 2. skips must never produce ok
    t.record_skip("conformance-test")
    assert t.snapshot()["status"] != "ok", "skip produced ok"

    # 3. empty evidence is rejected
    with pytest.raises(ValueError):
        t.record_success(evidence={})

    # 4. explicit success with evidence is the only path to ok
    t.record_success(evidence={"conformance": 1})
    assert t.snapshot()["status"] == "ok", "explicit success did not produce ok"

    # 5. failure flips status immediately and counts
    t.record_failure("boom")
    snap = t.snapshot()
    assert snap["status"] == "failing", "failure did not flip status"
    assert snap["consecutive_failures"] >= 1

    # 6. persistence round-trip (only meaningful for persist=True factories)
    t2 = make_tracker()
    if t2.persist:
        assert t2.snapshot()["source"] == "persisted"
        assert t2.snapshot()["last_success_at"] is not None


def make_tracker_factory(**overrides):
    def factory():
        kwargs = dict(interval_seconds=60, persist=False)
        kwargs.update(overrides)
        name = "conformance-" + str(time.time())
        return LivenessTracker(name, **kwargs)

    return factory
