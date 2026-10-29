"""Only a universe whose status is exactly "ok" admits scoring or completes a snapshot (#1484, review item 5).

The universe provider writes "ok", "degraded" or "emergency_registry"; a receipt built after an error says
"unknown". Anything else (a stale marker, an empty string, a missing key, a different spelling) is not a
verdict the reader can trust, so it fails closed.
"""

from __future__ import annotations

import copy

import pytest

from internal.council import score_snapshots as snaps
from internal.council import snapshot_coverage as cov
from tests.score_snapshot_testutil import complete_snapshot_payload

_MISSING = object()
_NOT_OK = ["stale", "", None, _MISSING, "unknown", "emergency_registry", "degraded", "OK", " ok", "ok ", 1, True]
_IDS = ["stale", "empty", "none", "missing", "unknown", "emergency", "degraded", "upper", "lead_space", "trail_space", "int", "bool"]


def _receipt(status):
    receipt = copy.deepcopy(complete_snapshot_payload()["coverage"]["membership"])
    receipt.update({"degraded": False, "cap_reached": False, "refresh_incomplete": False})
    if status is _MISSING:
        receipt.pop("universe_status", None)
    else:
        receipt["universe_status"] = status
    return receipt


def _snapshot(status):
    snap = copy.deepcopy(complete_snapshot_payload())
    snap["coverage"]["membership"] = _receipt(status)
    return snap


def test_ok_is_admitted_and_complete():
    assert cov.membership_allows_admission(_receipt("ok")) is True
    assert cov.membership_admission_block_reason(_receipt("ok")) is None
    assert snaps.is_complete_snapshot(_snapshot("ok")) is True


@pytest.mark.parametrize("status", _NOT_OK, ids=_IDS)
def test_any_other_status_blocks_admission_with_a_named_reason(status):
    receipt = _receipt(status)
    assert cov.membership_allows_admission(receipt) is False
    assert cov.membership_admission_block_reason(receipt) is not None


@pytest.mark.parametrize("status", _NOT_OK, ids=_IDS)
def test_any_other_status_is_not_a_complete_snapshot(status):
    assert snaps.is_complete_snapshot(_snapshot(status)) is False


def test_stale_status_is_reported_as_such():
    assert cov.membership_admission_block_reason(_receipt("stale")) == "universe_status_not_ok"
    assert cov.membership_admission_block_reason(_receipt(_MISSING)) == "universe_status_not_ok"
