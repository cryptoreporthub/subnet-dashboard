"""The receipt's own block_hash and rpc must agree with the chain read it embeds (#1484, review item 3)."""

from __future__ import annotations

import copy

import pytest

from internal.council import score_snapshots as snaps
from tests.score_snapshot_testutil import complete_snapshot_payload

_MISSING = object()


def _snapshot_with_receipt(**overrides):
    snap = copy.deepcopy(complete_snapshot_payload())
    membership = snap["coverage"]["membership"]
    for key, value in overrides.items():
        if value is _MISSING:
            membership.pop(key, None)
        else:
            membership[key] = value
    return snap


def test_untouched_fixture_is_complete():
    assert snaps.is_complete_snapshot(_snapshot_with_receipt()) is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"block_hash": "0x" + "00" * 32},
        {"block_hash": _MISSING},
        {"block_hash": None},
        {"rpc": "blockmachine"},
        {"rpc": _MISSING},
        {"rpc": None},
    ],
    ids=["block_hash_differs", "block_hash_missing", "block_hash_none", "rpc_differs", "rpc_missing", "rpc_none"],
)
def test_receipt_top_level_chain_fields_must_equal_the_chain_read(overrides):
    assert snaps.is_complete_snapshot(_snapshot_with_receipt(**overrides)) is False
