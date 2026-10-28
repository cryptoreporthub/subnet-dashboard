"""is_complete_snapshot admits only what membership and coverage both allow (MC act-on 1)."""

from __future__ import annotations

import pytest

from internal.council.score_snapshots import is_complete_snapshot
from tests.score_snapshot_testutil import complete_snapshot_payload


def test_complete_payload_is_admitted():
    assert is_complete_snapshot(complete_snapshot_payload()) is True


@pytest.mark.parametrize("phase", ["day", "hour"])
def test_incomplete_coverage_phase_is_rejected(phase):
    snap = complete_snapshot_payload()
    snap["coverage"][phase]["complete"] = False
    assert is_complete_snapshot(snap) is False


@pytest.mark.parametrize("status", ["unknown", "emergency_registry"])
def test_membership_status_that_admission_blocks_is_rejected(status):
    snap = complete_snapshot_payload()
    snap["coverage"]["membership"]["universe_status"] = status
    assert is_complete_snapshot(snap) is False


@pytest.mark.parametrize("horizon", ["day", "hour"])
def test_a_row_outside_the_membership_in_one_horizon_is_rejected(horizon):
    snap = complete_snapshot_payload()
    snap[horizon].append({"netuid": 99, "total_score": 1.0, "name": "X"})
    assert is_complete_snapshot(snap) is False


@pytest.mark.parametrize("horizon", ["day", "hour"])
def test_a_member_missing_from_one_horizon_is_rejected(horizon):
    snap = complete_snapshot_payload()
    snap[horizon].pop()
    assert is_complete_snapshot(snap) is False
