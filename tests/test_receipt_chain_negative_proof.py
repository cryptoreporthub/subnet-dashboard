"""Receipt-level proof of the owner rules on the ChainRead model (#1531).

Chain beats TaoMarketCap, a deregistered row keeps its 48h grace, and root is never removed.
Built with the real SnapshotBuilder and read back through load_membership_receipt.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from internal.council import snapshot_coverage as cov
from internal.subnet_universe import (
    STALE_GRACE_SECONDS,
    SnapshotBuilder,
    UniverseSnapshot,
    _reset_provider_for_tests,
    _validity_entry,
)
from tests.test_subnet_universe import _patch_registration

CHAIN = [1, 2, 3]
UNIVERSE = [0, 1, 2, 3, 4]
GONE = 4


@pytest.fixture(autouse=True)
def _isolated_universe(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _reset_provider_for_tests()
    yield
    _reset_provider_for_tests()


def _prior(netuids, *, negative_since=None):
    validity = {str(n): _validity_entry(validity="positive", sources=["taomarketcap"]) for n in netuids}
    if negative_since is not None:
        validity[str(GONE)] = _validity_entry(
            validity="negative", sources=["taomarketcap"], disputed=True, negative_since=negative_since
        )
    return UniverseSnapshot(
        netuids=tuple(netuids),
        rows=tuple({"netuid": n, "name": f"SN{n}"} for n in netuids),
        resolved_at=datetime.now(timezone.utc).isoformat(),
        status="ok",
        degraded=False,
        validity_map=validity,
    )


def _builder(*, tmc_lists_root=True):
    listed = [n for n in UNIVERSE if tmc_lists_root or n != 0]
    rows = {n: {"netuid": n, "name": f"SN{n}"} for n in listed}
    return SnapshotBuilder(tmc_fetch=lambda: (set(listed), rows, True))


def _receipt(snapshot):
    import internal.subnet_universe as universe

    original = universe.get_snapshot
    universe.get_snapshot = lambda: snapshot
    try:
        return cov.load_membership_receipt()
    finally:
        universe.get_snapshot = original


def _build(monkeypatch, prior, *, tmc_lists_root=True):
    _patch_registration(monkeypatch, CHAIN)
    return _builder(tmc_lists_root=tmc_lists_root).build(prior).snapshot


def _ago(seconds):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def test_chain_negative_subnet_with_row_data_leaves_expected_at_once_and_keeps_its_row(monkeypatch):
    built = _build(monkeypatch, _prior(UNIVERSE))
    receipt = _receipt(built)
    assert receipt["expected_netuids"] == CHAIN
    assert GONE not in receipt["expected_netuids"]
    assert built.validity_map[str(GONE)]["validity"] == "negative"
    assert built.validity_map[str(GONE)]["negative_since"]
    assert GONE in built.netuids
    assert GONE in {row["netuid"] for row in built.rows}


def test_row_inside_the_48h_grace_stays_and_the_row_leaves_after_it(monkeypatch):
    inside = _build(monkeypatch, _prior(UNIVERSE, negative_since=_ago(STALE_GRACE_SECONDS - 3600)))
    assert GONE in inside.netuids
    assert GONE not in _receipt(inside)["expected_netuids"]

    outside = _build(monkeypatch, _prior(UNIVERSE, negative_since=_ago(STALE_GRACE_SECONDS + 60)))
    assert GONE not in outside.netuids
    assert _receipt(outside)["expected_netuids"] == CHAIN


def test_root_stays_in_the_membership_through_a_chain_negative_and_after_grace(monkeypatch):
    for negative_since in (None, _ago(STALE_GRACE_SECONDS + 60)):
        built = _build(monkeypatch, _prior(UNIVERSE, negative_since=negative_since))
        receipt = _receipt(built)
        assert 0 in built.netuids
        assert receipt["root_netuid_in_membership"] is True
        assert 0 not in receipt["expected_netuids"]  # expected is the scored set: positive netuids only


def test_root_stays_when_a_probe_reports_it_unregistered(monkeypatch):
    builder = SnapshotBuilder(
        tmc_fetch=lambda: ({0, 1}, {0: {"netuid": 0}, 1: {"netuid": 1}}, True),
        probe_fetch=lambda netuids, deadline: ({0: False, 1: True}, True),
    )
    built = builder.build(_prior([0, 1])).snapshot
    assert 0 in built.netuids
    assert built.validity_map["0"]["validity"] != "negative"
    assert _receipt(built)["root_netuid_in_membership"] is True


def test_a_chain_read_adds_root_even_when_neither_the_prior_universe_nor_tmc_listed_it(monkeypatch):
    built = _build(monkeypatch, _prior([1, 2, 3, GONE]), tmc_lists_root=False)
    assert 0 in built.netuids
    assert _receipt(built)["root_netuid_in_membership"] is True
