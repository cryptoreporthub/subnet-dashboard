"""The chain read is the only membership truth in is_complete_snapshot (MC act-on 3, #1484)."""

import copy

import pytest

from internal.council import score_snapshots as snaps
from tests.score_snapshot_testutil import complete_snapshot_payload, complete_snapshot_rows

IDS = [2, 3, 4]


def _base():
    return complete_snapshot_payload(day_rows=complete_snapshot_rows(IDS))


MUTATIONS = {
    "day_expected_contradicts_chain": lambda p: p["coverage"]["day"].update(expected=[999]),
    "day_expected_missing_a_chain_member": lambda p: p["coverage"]["day"].update(expected=[2, 3]),
    "day_expected_has_extra_member": lambda p: p["coverage"]["day"].update(expected=[2, 3, 4, 999]),
    "membership_expected_contradicts_chain": lambda p: p["coverage"]["membership"].update(expected_netuids=[1, 2]),
    "membership_refresh_incomplete": lambda p: p["coverage"]["membership"].update(refresh_incomplete=True),
    "membership_degraded": lambda p: p["coverage"]["membership"].update(degraded=True),
    "membership_cap_reached": lambda p: p["coverage"]["membership"].update(cap_reached=True),
    "membership_not_fresh": lambda p: p["coverage"]["membership"].update(fresh=False),
    "hour_empty": lambda p: p.update(hour=[]),
    "hour_missing_a_chain_member": lambda p: p.update(hour=p["hour"][:-1]),
}


def test_control_base_snapshot_is_complete():
    assert snaps.is_complete_snapshot(_base()) is True


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_inconsistent_snapshot_is_not_complete(name):
    assert snaps.is_complete_snapshot(_base()) is True
    payload = copy.deepcopy(_base())
    MUTATIONS[name](payload)
    assert snaps.is_complete_snapshot(payload) is False
