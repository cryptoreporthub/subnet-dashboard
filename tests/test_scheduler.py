"""Tests for the AdversarialScheduler and its LivenessTracker adoption (issue #1032)."""

import time

import pytest

from internal.scheduler import AdversarialScheduler
from tests.liveness_conformance import assert_liveness_compliant, make_tracker_factory


def _scheduler(**kw):
    kw.setdefault("stake_threshold_tao", 400000)
    kw.setdefault("registry_path", "config/registry.json")
    return AdversarialScheduler(**kw)


def test_state_includes_subnet_count():
    scheduler = _scheduler()
    state = scheduler.state()
    assert "last_subnet_count" in state
    assert state["last_subnet_count"] == 0


def test_state_last_run_ok_never_ok_on_fresh_or_skip():
    scheduler = _scheduler()
    assert scheduler.state()["last_run_ok"] is not True
    scheduler._last_run_timestamp = time.time()
    out = scheduler.check_and_run()
    assert out["skipped"] is True
    assert scheduler.state()["last_run_ok"] is not True
    assert scheduler.liveness.snapshot()["consecutive_skips"] >= 1


def test_failure_is_not_ok():
    scheduler = _scheduler()
    scheduler.registry_path = "/nonexistent/registry.json"
    scheduler.run_once()
    assert scheduler.state()["last_run_ok"] is not True
    assert scheduler.liveness.snapshot()["status"] == "failing"


def test_tracker_is_liveness_compliant():
    sched = _scheduler()
    assert_liveness_compliant(lambda: sched.liveness)


def test_conformance_factory():
    assert_liveness_compliant(make_tracker_factory())
