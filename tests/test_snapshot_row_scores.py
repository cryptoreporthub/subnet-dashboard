"""A row without a score is not a scored row (#1484 round 3, item 3).

`_row_ids` is only called by `is_complete_snapshot`, to compare the day and hour row sets with the
chain read. Completeness means "every expected netuid was scored", and the producer writes
`total_score = float(score or 0)` for every row it emits, so a row that has no finite numeric score
did not come from the producer (a hand-edited or partly written file). Counting it would let a
snapshot with empty rows pass as complete and be served as the picks' source.
"""

from __future__ import annotations

import copy

import pytest

from internal.council import score_snapshots as snaps
from tests.score_snapshot_testutil import complete_snapshot_payload

pytestmark = pytest.mark.usefixtures("usable_soul_map")


def _strip_to_netuid(row):
    netuid = row["netuid"]
    row.clear()
    row["netuid"] = netuid


def _with_row(horizon, index, mutate):
    snap = copy.deepcopy(complete_snapshot_payload())
    mutate(snap[horizon][index])
    return snap


def test_the_untouched_fixture_is_complete():
    assert snaps.is_complete_snapshot(complete_snapshot_payload()) is True


@pytest.mark.parametrize("horizon", ["day", "hour"])
@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: row.pop("total_score"),
        lambda row: row.update(total_score=None),
        lambda row: row.update(total_score="5.0"),
        lambda row: row.update(total_score=True),
        lambda row: row.update(total_score=float("nan")),
        lambda row: row.update(total_score=float("inf")),
        _strip_to_netuid,
    ],
    ids=["missing", "none", "string", "bool", "nan", "inf", "netuid_only"],
)
def test_a_row_without_a_finite_numeric_score_makes_the_snapshot_incomplete(horizon, mutate):
    assert snaps.is_complete_snapshot(_with_row(horizon, 0, mutate)) is False


@pytest.mark.parametrize("horizon", ["day", "hour"])
@pytest.mark.parametrize("score", [0, 0.0, -1.5, 87])
def test_a_zero_negative_or_integer_score_is_still_a_score(horizon, score):
    assert snaps.is_complete_snapshot(_with_row(horizon, 0, lambda row: row.update(total_score=score))) is True


@pytest.mark.parametrize("horizon", ["day", "hour"])
@pytest.mark.parametrize("huge", [10**400, -(10**400)], ids=["positive", "negative"])
def test_an_oversized_integer_score_is_rejected_without_raising(horizon, huge):
    """``math.isfinite(10**400)`` raises OverflowError; is_complete_snapshot promises it never raises (#1484 Ditto r5)."""
    snap = _with_row(horizon, 0, lambda row: row.update(total_score=huge))

    assert snaps.is_complete_snapshot(snap) is False


def test_a_large_but_representable_integer_score_is_still_a_score():
    snap = _with_row("day", 0, lambda row: row.update(total_score=10**300))

    assert snaps.is_complete_snapshot(snap) is True
