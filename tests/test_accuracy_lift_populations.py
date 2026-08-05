"""Phase A — accuracy_lift population buckets."""

from __future__ import annotations

from internal.accuracy_lift.populations import (
    is_council_trust_row,
    is_published_council_row,
    is_shadow_row,
    pick_source_bucket,
    population_of,
)


def _row(**kwargs):
    base = {"correct": True, "outcome": "hit"}
    base.update(kwargs)
    return base


def test_shadow_by_flag_and_pick_source():
    assert is_shadow_row(_row(shadow=True)) is True
    assert is_shadow_row(_row(pick_source="council_shadow")) is True
    assert is_shadow_row(_row(pick_source="council")) is False


def test_missing_pick_source_counts_as_council():
    row = _row()
    assert pick_source_bucket(row) == "council"
    assert is_published_council_row(row) is True
    assert is_council_trust_row(row) is True


def test_pump_lead_excluded_from_council_trust():
    row = _row(pick_source="pump_lead", correct=False)
    assert population_of(row) == "pump_lead"
    assert pick_source_bucket(row) == "pump_lead"
    assert is_council_trust_row(row) is False
    assert is_published_council_row(row) is False


def test_shadow_population_bucket():
    row = _row(pick_source="council_shadow")
    assert population_of(row) == "shadow"
    assert pick_source_bucket(row) == "council_shadow"
