"""The universe layer carries a chain read; only receipt/admission demands a pinned (64-hex) block (#1484 round 3).

main's tests/test_subnet_universe.py pins the registration read with block "0xabc" and builds through the
injected-probe seam; it must pass unedited. These tests pin what keeps that safe: nothing minted or
accepted at the universe layer can be admitted unless its block hash is a real 64-hex pin.
"""

from __future__ import annotations

import copy

import pytest

from internal.chain_price.membership import read_chain_membership
from internal.chain_read import ChainRead
from internal.council import score_snapshots as snaps
from internal.council import snapshot_coverage as cov
from internal.subnet_universe import SnapshotBuilder, UniverseSnapshot
from tests.score_snapshot_testutil import complete_snapshot_payload
from tests.test_subnet_universe import _prior_snapshot, universe_tmp  # noqa: F401  (fixture)

PINNED_HASH = "0x" + "ab" * 32


def _patch_registration(monkeypatch, members, *, pin=(PINNED_HASH, "ok"), read="ok"):
    class _Reader:
        def __init__(self, *args, **kwargs):
            self.provider_served = "fixture"

        def pin_finalized_head(self):
            return pin

        def call_fn(self):
            return lambda method, params: (None, "ok")

    monkeypatch.setattr("internal.chain_price.reader.ChainReader", _Reader)
    monkeypatch.setattr(
        "internal.chain_price.membership.get_member_netuids",
        lambda call, at_hash: (list(members) if read == "ok" else [], read),
    )


def _tmc(*netuids):
    return lambda: (set(netuids), {n: {"netuid": n} for n in netuids}, True)


def _receipt_for(monkeypatch, snapshot):
    import internal.subnet_universe as universe

    monkeypatch.setattr(universe, "get_snapshot", lambda: snapshot)
    return cov.load_membership_receipt()


# --- moved from tests/test_subnet_universe.py (the branch's additions), with a 64-hex fixture block ---


def test_build_carries_the_chain_read_it_resolved_from(universe_tmp, monkeypatch):
    _patch_registration(monkeypatch, [1, 2, 3])
    built = SnapshotBuilder(tmc_fetch=_tmc(1, 2, 3)).build(_prior_snapshot([1, 2, 3])).snapshot
    assert built.chain == ChainRead(PINNED_HASH, (1, 2, 3), "fixture")


@pytest.mark.parametrize("kwargs", [{"read": "invalid"}, {"pin": (None, "rpc_error")}])
def test_build_has_no_chain_when_the_registration_read_fails(universe_tmp, monkeypatch, kwargs):
    _patch_registration(monkeypatch, [1, 2, 3], **kwargs)
    assert SnapshotBuilder(tmc_fetch=_tmc(1, 2, 3)).build(_prior_snapshot([1, 2, 3])).snapshot.chain is None


def test_chain_is_not_carried_across_a_failed_cycle(universe_tmp, monkeypatch):
    _patch_registration(monkeypatch, [1, 2, 3])
    builder = SnapshotBuilder(tmc_fetch=_tmc(1, 2, 3))
    first = builder.build(_prior_snapshot([1, 2, 3])).snapshot
    assert first.chain is not None
    _patch_registration(monkeypatch, [1, 2, 3], pin=(None, "rpc_error"))
    assert builder.build(first).snapshot.chain is None


def test_chain_round_trips_through_the_persisted_snapshot(universe_tmp, monkeypatch):
    _patch_registration(monkeypatch, [1, 2])
    built = SnapshotBuilder(tmc_fetch=_tmc(1, 2)).build(_prior_snapshot([1, 2])).snapshot
    assert UniverseSnapshot.from_dict(built.to_dict()).chain == built.chain


@pytest.mark.parametrize(
    "chain",
    [None, "x", {"block_hash": "0xabc", "netuids": [1]}, {"block_hash": "0x" + "ab" * 32, "netuids": [2, 1]}],
)
def test_a_missing_or_malformed_persisted_chain_loads_as_none(chain):
    payload = _prior_snapshot([1, 2]).to_dict()
    payload["chain"] = chain
    assert UniverseSnapshot.from_dict(payload).chain is None
    payload.pop("chain")
    assert UniverseSnapshot.from_dict(payload).chain is None


# --- new: a short block hash is accepted by the read, never by admission ---


def test_the_registration_read_accepts_a_short_pin_but_it_is_not_a_pinned_block(monkeypatch):
    _patch_registration(monkeypatch, [1, 2], pin=("0xabc", "ok"))
    chain, outcome = read_chain_membership(__import__("internal.chain_price.reader", fromlist=["ChainReader"]).ChainReader())
    assert outcome == "ok"
    assert chain == ChainRead("0xabc", (1, 2), "fixture")
    assert chain.is_pinned is False
    assert ChainRead(PINNED_HASH, (1, 2), "fixture").is_pinned is True


def test_a_malformed_block_hash_is_still_an_invalid_read(monkeypatch):
    for bad in ("abc", "0x", "0xZZ", "", "0x" + "ab" * 40 + "\n"):
        _patch_registration(monkeypatch, [1, 2], pin=(bad, "ok"))
        chain, outcome = read_chain_membership(__import__("internal.chain_price.reader", fromlist=["ChainReader"]).ChainReader())
        assert chain is None, bad


def test_a_universe_built_on_a_short_pin_is_never_admitted(universe_tmp, monkeypatch):
    _patch_registration(monkeypatch, [1, 2, 3], pin=("0xabc", "ok"))
    built = SnapshotBuilder(tmc_fetch=_tmc(1, 2, 3)).build(_prior_snapshot([1, 2, 3])).snapshot
    assert built.chain is not None and built.chain.block_hash == "0xabc"
    receipt = _receipt_for(monkeypatch, built)
    assert receipt["expected_netuids"] == [1, 2, 3]  # the universe layer still reports what it read
    assert cov.membership_allows_admission({**receipt, "universe_status": "ok", "fresh": True}) is False
    assert cov.membership_admission_block_reason({**receipt, "universe_status": "ok", "fresh": True}) == (
        "membership_without_chain_provenance"
    )


def test_a_snapshot_stamped_with_a_short_block_hash_is_not_complete():
    snap = copy.deepcopy(complete_snapshot_payload())
    membership = snap["coverage"]["membership"]
    membership["block_hash"] = membership["chain"]["block_hash"] = "0xabc"
    snap["provenance"]["membership_block_hash"] = "0xabc"
    assert snaps.is_complete_snapshot(snap) is False


def test_a_short_pin_does_not_survive_a_restart(universe_tmp, monkeypatch):
    _patch_registration(monkeypatch, [1, 2], pin=("0xabc", "ok"))
    built = SnapshotBuilder(tmc_fetch=_tmc(1, 2)).build(_prior_snapshot([1, 2])).snapshot
    assert UniverseSnapshot.from_dict(built.to_dict()).chain is None


# --- new: the injected-probe seam derives a chain from the probe's own result, unpinned ---


def test_an_injected_probe_yields_an_unpinned_chain_from_its_own_result(universe_tmp, monkeypatch):
    builder = SnapshotBuilder(
        tmc_fetch=_tmc(1, 2, 3),
        probe_fetch=lambda netuids, deadline: ({n: n in (1, 2) for n in netuids}, True),
    )
    built = builder.build(_prior_snapshot([1, 2, 3])).snapshot
    assert built.chain is not None
    assert built.chain.netuids == (1, 2)  # what the probe observed registered
    assert built.chain.is_pinned is False


def test_an_unpinned_probe_chain_is_never_admitted(universe_tmp, monkeypatch):
    builder = SnapshotBuilder(
        tmc_fetch=_tmc(1, 2, 3),
        probe_fetch=lambda netuids, deadline: ({n: n in (1, 2, 3) for n in netuids}, True),
    )
    built = builder.build(_prior_snapshot([1, 2, 3])).snapshot
    receipt = {**_receipt_for(monkeypatch, built), "universe_status": "ok", "fresh": True}
    assert receipt["expected_netuids"] == [1, 2, 3]
    assert cov.membership_allows_admission(receipt) is False
    assert UniverseSnapshot.from_dict(built.to_dict()).chain is None


def test_a_failed_probe_mints_no_chain(universe_tmp):
    builder = SnapshotBuilder(
        tmc_fetch=_tmc(1, 2),
        probe_fetch=lambda netuids, deadline: ({}, False),
    )
    assert builder.build(_prior_snapshot([1, 2])).snapshot.chain is None


def test_an_incomplete_probe_never_mints_a_chain_even_with_partial_verdicts(universe_tmp):
    builder = SnapshotBuilder(
        tmc_fetch=_tmc(1, 2),
        probe_fetch=lambda netuids, deadline: ({1: True, 2: True}, False),
    )
    assert builder.build(_prior_snapshot([1, 2])).snapshot.chain is None
