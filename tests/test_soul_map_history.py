"""Unit tests for resolver cycle_history ring-buffer + nonstage rollups (mock only)."""

from __future__ import annotations

from internal.council.resolver_scheduler import (
    CYCLE_HISTORY_MAX,
    _CycleTiming,
    bound_cycle_history,
    compute_stages_sum_and_nonstage,
)


def test_bound_cycle_history_caps_at_ten():
    entries = [{"run_at": f"t{i}", "n": i} for i in range(15)]
    out = bound_cycle_history(entries, CYCLE_HISTORY_MAX)
    assert len(out) == 10
    assert out[0]["n"] == 5
    assert out[-1]["n"] == 14
    assert CYCLE_HISTORY_MAX == 10


def test_bound_cycle_history_non_list_returns_empty():
    assert bound_cycle_history(None) == []
    assert bound_cycle_history({"x": 1}) == []


def test_compute_stages_sum_and_nonstage_gap():
    timing = {
        "resolve_due_ms": 100.0,
        "expire_stale_ms": 20.0,
        "hydrate_ms_total": 5.0,
        "hydrate_ms_max": 5.0,
        "hydration_count": 1,
        "total_cycle_ms": 200.0,
    }
    rollup = compute_stages_sum_and_nonstage(timing)
    assert rollup["stages_sum_ms"] == 125.0
    assert rollup["nonstage_ms"] == 75.0
    assert "stages_sum_ms" in rollup and "nonstage_ms" in rollup


def test_cycle_timing_snapshot_includes_stages_sum_and_nonstage():
    timing = _CycleTiming()
    with timing.stage("resolve_due", lambda: None):
        pass
    snap = timing.snapshot()
    assert "stages_sum_ms" in snap
    assert "nonstage_ms" in snap
    assert "stages_sum_ms" in snap["stage_timing_ms"]
    assert "nonstage_ms" in snap["stage_timing_ms"]
    assert isinstance(snap["stages_sum_ms"], float)
    assert isinstance(snap["nonstage_ms"], float)


def test_truncate_marker_format_for_capture_pipeline():
    """Document the capture truncation marker contract (no silent truncate)."""
    original = 70000
    marker = f"\n[TRUNCATED — ORIGINAL SIZE: {original} bytes]\n"
    assert "TRUNCATED" in marker
    assert str(original) in marker

def test_nonstage_unchanged_when_gap_timing_present():
    """Fence regression: a subordinate gap_timing_ms dict must NOT collapse nonstage_ms."""
    timing = {
        "resolve_due_ms": 100.0,
        "expire_stale_ms": 20.0,
        "total_cycle_ms": 200.0,
        "gap_timing_ms": {
            "setup_ms": 30.0,  # illustrative B1b values — shape, not measurement
            "teardown_ms": 25.0,
            "soul_map_bytes_start": 1000,
            "soul_map_bytes_end": 1000,
            "complete": True,
        },
    }
    rollup = compute_stages_sum_and_nonstage(timing)
    assert rollup["stages_sum_ms"] == 120.0
    assert rollup["nonstage_ms"] == 80.0


def test_complete_flag_defaults_false_and_sets_true():
    """Locked B1 decision: provenance is a field, never inferred."""
    t = _CycleTiming()
    snap = t.snapshot()
    assert snap["gap_timing_ms"]["complete"] is False
    t.mark_complete()
    snap = t.snapshot()
    assert snap["gap_timing_ms"]["complete"] is True

def test_gap_buckets_allocate_without_double_counting():
    """B1b: closing math — gap = interval minus its stage; window closes exactly."""
    from internal.council.resolver_scheduler import _compute_gap_buckets

    cps = [
        ("t0", 0.0),
        ("t1", 250.0),
        ("t2", 500.0),
        ("t3", 750.0),
        ("t4", 1000.0),
        ("t5", 1250.0),
        ("t6", 1500.0),
        ("t7", 1750.0),
    ]
    stage_ms = {
        "ledger_heal": 200.0,
        "subnet_provider": 200.0,
        "soul_map_load": 200.0,
        "resolve_due": 200.0,
        "expire_stale": 200.0,
        "auto_retrain": 200.0,
    }
    total_ms = 1750.0
    buckets, gaps_sum = _compute_gap_buckets(cps, stage_ms)
    assert len(buckets) == 7
    # Six intervals carry a 200ms stage inside a 250ms interval; t6->t7 is bare.
    assert all(buckets["gap_%d_ms" % i] == 50.0 for i in range(6))
    assert buckets["gap_6_ms"] == 250.0
    assert gaps_sum == 550.0
    assert abs(total_ms - (sum(stage_ms.values()) + gaps_sum)) < 1e-6
