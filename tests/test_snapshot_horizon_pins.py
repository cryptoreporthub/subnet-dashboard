"""Each horizon's flags and declared expected list are pinned to the chain read (#1484, review extras)."""

from __future__ import annotations

import copy

import pytest

from internal.council import score_snapshots as snaps
from tests.score_snapshot_testutil import complete_snapshot_payload


def _snapshot(horizon=None, **block):
    snap = copy.deepcopy(complete_snapshot_payload())
    if horizon:
        snap["coverage"][horizon].update(block)
    return snap


@pytest.mark.parametrize("horizon", ["day", "hour"])
@pytest.mark.parametrize("truthy", [1, "yes", "true", [1], {"a": 1}, 1.0], ids=["int", "yes", "true", "list", "dict", "float"])
def test_a_truthy_horizon_flag_is_not_complete(horizon, truthy):
    assert snaps.is_complete_snapshot(_snapshot(horizon, complete=truthy)) is False


@pytest.mark.parametrize("horizon", ["day", "hour"])
@pytest.mark.parametrize("falsy", [False, None, 0, "", "False"], ids=["false", "none", "zero", "empty", "str_false"])
def test_a_falsy_horizon_flag_is_not_complete(horizon, falsy):
    assert snaps.is_complete_snapshot(_snapshot(horizon, complete=falsy)) is False


def test_hour_expected_equal_to_the_chain_read_is_complete():
    assert snaps.is_complete_snapshot(_snapshot("hour", expected=[2, 3])) is True


@pytest.mark.parametrize(
    "declared",
    [[2], [2, 3, 4], [2, 4], [3, 2, 2], [], "2,3", {"2": 1}, [2, "3"], [2, True], [2, 3.0], 7],
    ids=["missing_one", "extra", "wrong_member", "duplicate", "empty", "string", "dict", "str_member", "bool_member", "float_member", "int"],
)
def test_hour_expected_that_disagrees_with_the_chain_read_is_not_complete(declared):
    assert snaps.is_complete_snapshot(_snapshot("hour", expected=declared)) is False


def test_hour_expected_in_any_order_is_the_same_set():
    assert snaps.is_complete_snapshot(_snapshot("hour", expected=[3, 2])) is True
