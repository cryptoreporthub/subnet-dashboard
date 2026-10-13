"""Phase 1 snapshot coverage telemetry — unit checks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from internal.council import snapshot_coverage as cov
from internal.subnet_universe import UniverseSnapshot, _validity_entry


@pytest.fixture(autouse=True)
def _reset_phase1_state():
    cov.reset_phase1_cycle_state_for_tests()
    yield
    cov.reset_phase1_cycle_state_for_tests()


def test_env_int_treats_empty_as_default(monkeypatch):
    monkeypatch.setenv("SCORE_SNAPSHOT_MAX_SUBNETS", "")
    assert cov.env_int("SCORE_SNAPSHOT_MAX_SUBNETS", 7) == 7


def test_membership_fresh_seam():
    now = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
    resolved = (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    assert cov.membership_fresh(resolved, now=now) is True
    stale = (now - timedelta(days=3)).isoformat().replace("+00:00", "Z")
    assert cov.membership_fresh(stale, now=now) is False


def test_membership_fail_closed_on_emergency_registry():
    receipt = {
        "fresh": True,
        "universe_status": "emergency_registry",
        "degraded": True,
        "cap_reached": False,
        "refresh_incomplete": False,
    }
    assert cov.membership_allows_complete(receipt) is False


def test_cap_reached_ok_not_complete():
    receipt = {
        "fresh": True,
        "universe_status": "ok",
        "degraded": False,
        "cap_reached": True,
        "refresh_incomplete": False,
    }
    block = cov.build_coverage_block(
        receipt=receipt,
        day_expected=[1, 2],
        day_succeeded=[1, 2],
        day_failed=[],
        hour_succeeded=[1, 2],
        hour_failed=[],
        hour_copied_from_day=True,
        capped_out=0,
        selection_policy="full",
        subnet_source="registry",
        published=True,
        timing={"build_wall_seconds": 1.0, "publish_wall_seconds": 0.01},
    )
    assert block["complete"] is False


def test_horizon_attempted_uses_call_site_ids_not_expected_len():
    receipt = {
        "fresh": True,
        "universe_status": "ok",
        "degraded": False,
        "cap_reached": False,
        "refresh_incomplete": False,
        "expected_netuids": [1, 2, 3],
    }
    block = cov.build_coverage_block(
        receipt=receipt,
        day_expected=[1, 2, 3],
        day_succeeded=[1],
        day_failed=[{"netuid": 2, "stage": "day", "error_class": "RuntimeError"}],
        hour_succeeded=[1],
        hour_failed=[],
        day_attempted=[1, 2],
        hour_attempted=[],
        hour_copied_from_day=True,
        capped_out=0,
        selection_policy="full",
        subnet_source="registry",
        published=True,
        timing={"build_wall_seconds": 1.0},
    )
    assert block["day"]["attempted"] == 2
    assert block["day"]["attempted_netuids"] == [1, 2]
    assert block["hour"]["attempted"] == 0
    assert block["hour"]["hour_copied_from_day"] is True


def test_horizon_id_equality_required_for_complete():
    receipt = {
        "fresh": True,
        "universe_status": "ok",
        "degraded": False,
        "cap_reached": False,
        "refresh_incomplete": False,
    }
    block = cov.build_coverage_block(
        receipt=receipt,
        day_expected=[1, 2],
        day_succeeded=[1],
        day_failed=[{"netuid": 2, "stage": "day", "error_class": "RuntimeError"}],
        hour_succeeded=[1],
        hour_failed=[],
        hour_copied_from_day=True,
        capped_out=0,
        selection_policy="full",
        subnet_source="registry",
        published=True,
        timing={"build_wall_seconds": 2.0, "publish_wall_seconds": 0.02},
    )
    assert block["day"]["complete"] is False
    assert block["complete"] is False


def test_phase1_consecutive_partial_cycles_gate(monkeypatch):
    monkeypatch.setattr(cov, "PHASE1_CONSECUTIVE_PARTIAL_CYCLES", 2)
    partial = {"complete": False}
    assert cov.note_cycle(partial) == 1
    assert cov.note_cycle(partial) == 2
    assert cov.phase1_exit_gate_met() is True
    cov.note_cycle({"complete": True})
    assert cov.consecutive_partial_cycles() == 0


def test_membership_expected_is_full_set_not_tradable_shrink():
    rows = [{"netuid": 1}, {"netuid": 5}]
    assert cov.membership_scoring_expected([1, 2, 3]) == [1, 2, 3]
    assert cov.scoring_expected_netuids([1, 2, 3], rows) == [1, 2, 3]


def test_membership_scoring_empty_membership_admits_nothing():
    feed = [{"netuid": 1, "name": "One"}, {"netuid": 99, "name": "Extra"}]
    rows, meta = cov.membership_scoring_candidate_rows([], feed)
    assert rows == []
    assert meta["selection_basis"] == "membership_empty"
    assert meta["admitted_count"] == 0


def test_membership_scoring_gated_on_emergency_registry():
    feed = [{"netuid": 1, "name": "One"}, {"netuid": 2, "name": "Two"}]
    receipt = {
        "fresh": True,
        "universe_status": "emergency_registry",
        "degraded": True,
        "cap_reached": False,
        "refresh_incomplete": False,
        "expected_netuids": [1, 2],
    }
    rows, meta = cov.membership_scoring_candidate_rows([1, 2], feed, receipt=receipt)
    assert rows == []
    assert meta["selection_basis"] == "membership_gated"
    assert meta["admission_gate_reason"] == "emergency_registry"
    assert meta["expected_count"] == 2
    assert meta["membership_admission_allowed"] is False


def test_membership_scoring_gated_on_stale_membership():
    feed = [{"netuid": 1, "name": "One"}]
    receipt = {
        "fresh": False,
        "universe_status": "ok",
        "degraded": False,
        "cap_reached": False,
        "refresh_incomplete": False,
        "expected_netuids": [1],
    }
    rows, meta = cov.membership_scoring_candidate_rows([1], feed, receipt=receipt)
    assert rows == []
    assert meta["admission_gate_reason"] == "stale_membership"


def test_membership_scoring_candidates_exclude_feed_only_and_root():
    feed = [
        {"netuid": 0, "name": "Root"},
        {"netuid": 1, "name": "One"},
        {"netuid": 99, "name": "Deregistered-extra"},
    ]
    rows, meta = cov.membership_scoring_candidate_rows([1, 2], feed)
    assert [r["netuid"] for r in rows] == [1]
    assert meta["selection_basis"] == "membership"
    assert meta["missing_netuids"] == [2]
    assert meta["excluded_feed_only_count"] == 1
    assert 99 in (meta.get("excluded_feed_only_netuids") or [])


def test_membership_scoring_candidates_dedupe_by_netuid():
    feed = [{"netuid": 1, "name": "A"}, {"id": 1, "name": "Dup"}]
    rows, _meta = cov.membership_scoring_candidate_rows([1], feed)
    assert len(rows) == 1
    assert rows[0]["netuid"] == 1


def test_membership_scoring_candidates_use_universe_row_when_feed_missing():
    feed = [{"netuid": 1, "name": "FromFeed"}]
    membership_rows = [{"netuid": 2, "name": "FromUniverse"}]
    rows, meta = cov.membership_scoring_candidate_rows([1, 2], feed, membership_rows=membership_rows)
    assert [r["netuid"] for r in rows] == [1, 2]
    assert meta["admitted_count"] == 2


def test_coverage_timing_for_disk_carries_previous_publish():
    cov.reset_phase1_cycle_state_for_tests()
    cov.record_publish_wall_seconds(0.012)
    disk = cov.coverage_timing_for_disk({"build_wall_seconds": 1.0})
    assert disk["previous_publish_wall_seconds"] == 0.012
    assert "publish_wall_seconds" not in disk


def test_publish_gauge_reads_previous_from_disk_timing():
    cov.reset_phase1_cycle_state_for_tests()
    value = cov._publish_wall_gauge_value({"previous_publish_wall_seconds": 0.02})
    assert value == 0.02


def test_publish_gauge_prefers_process_local_over_disk_previous():
    cov.reset_phase1_cycle_state_for_tests()
    cov.record_publish_wall_seconds(0.05)
    value = cov._publish_wall_gauge_value({"previous_publish_wall_seconds": 0.02})
    assert value == 0.05


def test_legacy_hour_copied_infers_without_status_field():
    block = {
        "succeeded": [1, 2],
        "hour_copied_from_day": True,
        "attempted": 0,
    }
    assert cov._horizon_scored_count(block, "hour") == 0
    assert cov._horizon_copied_count(block, "hour") == 2


def test_explicit_hour_status_scored_overrides_legacy_flag():
    block = {
        "succeeded": [1, 2],
        "hour_copied_from_day": True,
        "status": "scored",
        "attempted": 2,
    }
    assert cov._horizon_scored_count(block, "hour") == 2
    assert cov._horizon_copied_count(block, "hour") == 0


def test_empty_tradable_set_is_known_not_unknown():
    receipt = {
        "fresh": True,
        "universe_status": "ok",
        "degraded": False,
        "cap_reached": False,
        "refresh_incomplete": False,
        "expected_netuids": [1, 2],
    }
    block = cov.build_coverage_block(
        receipt=receipt,
        day_expected=[1, 2],
        day_succeeded=[],
        day_failed=[],
        hour_succeeded=[],
        hour_failed=[],
        hour_copied_from_day=True,
        capped_out=0,
        selection_policy="full",
        subnet_source="registry",
        published=True,
        timing={"build_wall_seconds": 1.0},
        tradable_netuids=set(),
    )
    assert block["day"]["missing_not_admitted"] == [1, 2]
    assert block["day"]["unaccounted"] == [1, 2]


def test_horizon_tracks_missing_not_admitted():
    receipt = {
        "fresh": True,
        "universe_status": "ok",
        "degraded": False,
        "cap_reached": False,
        "refresh_incomplete": False,
        "expected_netuids": [1, 2],
    }
    block = cov.build_coverage_block(
        receipt=receipt,
        day_expected=[1, 2],
        day_succeeded=[1],
        day_failed=[],
        hour_succeeded=[1],
        hour_failed=[],
        hour_copied_from_day=True,
        capped_out=0,
        selection_policy="full",
        subnet_source="registry",
        published=True,
        timing={"build_wall_seconds": 1.0},
        tradable_netuids={1},
    )
    assert block["day"]["missing_not_admitted"] == [2]
    assert block["complete"] is False


def test_load_membership_receipt_from_snapshot(monkeypatch):
    snap = UniverseSnapshot(
        netuids=(0, 1, 2),
        rows=({"netuid": 1}, {"netuid": 2}),
        resolved_at="2026-10-11T00:00:00Z",
        status="ok",
        degraded=False,
        validity_map={
            "1": _validity_entry(validity="positive", sources=["taomarketcap"]),
            "2": _validity_entry(validity="positive", sources=["taomarketcap"]),
        },
    )
    monkeypatch.setattr(
        "internal.subnet_universe.get_snapshot",
        lambda: snap,
    )
    receipt = cov.load_membership_receipt()
    assert receipt["root_netuid_in_membership"] is True
    assert receipt["universe_status"] == "ok"
    assert 1 in receipt["expected_netuids"]
