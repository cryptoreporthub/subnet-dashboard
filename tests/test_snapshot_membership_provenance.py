"""Membership provenance on score snapshots (#1479 PR-B, act-on 1).

Real SnapshotBuilder / _read_chain / ChainReader code; only the RPC transport and the
TMC fetch are injected, replaying a recorded chain read.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from internal.chain_price import config as chain_cfg
from internal.chain_read import ChainRead
from internal import subnet_universe as su
from internal.council import snapshot_coverage as cov

FIXTURE = Path(__file__).parent / "fixtures" / "chain" / "bm_9280796.json"
RECORDED_HEAD = "0x72a82add74d481216a2f4b8f77e7729f88b2abf0654a9c6be89a3cf10f7cedd0"


class _ReplayClient:
    """Answers from the recorded block-9280796 read; counts calls."""

    def __init__(self, recorded):
        self._recorded = recorded
        self.calls = 0

    def _call_typed(self, method, params=None):
        self.calls += 1
        if method == "chain_getFinalizedHead":
            return RECORDED_HEAD
        return self._recorded[f"{method}|{json.dumps(params or [])}"]

    def query_storage_at(self, keys, at_hash):
        return self._call_typed("state_queryStorageAt", [keys, at_hash])


class _DeadClient:
    def _call_typed(self, method, params=None):
        raise RuntimeError("provider down")


@pytest.fixture
def recorded_providers(monkeypatch):
    recorded = json.loads(FIXTURE.read_text())
    providers = [("finney", _DeadClient()), ("blockmachine", _ReplayClient(recorded))]
    monkeypatch.setattr(chain_cfg, "rpc_provider_clients", lambda: providers)
    return providers


def test_membership_block_and_rpc_survive_builder_and_persist(recorded_providers):
    chain = su._read_chain()
    assert chain is not None
    assert chain.block_hash == RECORDED_HEAD
    assert chain.rpc == "blockmachine"  # finney failed; the provider that answered is the label

    def tmc():
        members = set(chain.netuids)
        return members, {n: {"netuid": n, "name": f"N{n}"} for n in members}, True

    built = su.SnapshotBuilder(tmc_fetch=tmc).build(None).snapshot
    assert built.chain is not None
    assert (built.chain.block_hash, built.chain.rpc) == (RECORDED_HEAD, "blockmachine")

    reloaded = su.UniverseSnapshot.from_dict(json.loads(json.dumps(built.to_dict())))
    assert (reloaded.chain.block_hash, reloaded.chain.rpc) == (RECORDED_HEAD, "blockmachine")


def test_rpc_is_a_provider_label_never_a_url():
    raw = {"block_hash": RECORDED_HEAD, "netuids": [1, 2]}
    assert ChainRead.parse({**raw, "rpc": "finney"}).rpc == "finney"
    assert ChainRead.parse(raw).rpc is None  # a universe file written before rpc existed still loads
    leaked = ChainRead.parse({**raw, "rpc": "https://rpc.example/?key=secret"})
    assert leaked is not None and leaked.rpc is None
    assert "secret" not in json.dumps(leaked.to_dict())


def _universe(chain_netuids, *, universe_netuids=None, block="ab", rpc="finney"):
    """A fresh, ok universe. ``universe_netuids`` may keep a grace row the chain no longer lists."""
    ids = tuple(universe_netuids if universe_netuids is not None else chain_netuids)
    return su.UniverseSnapshot(
        netuids=ids,
        rows=tuple({"netuid": n, "name": f"N{n}"} for n in ids),
        resolved_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        status="ok",
        degraded=False,
        chain=ChainRead("0x" + block * 32, tuple(sorted(chain_netuids)), rpc),
    )


def _receipt_for(monkeypatch, universe):
    monkeypatch.setattr(su, "get_snapshot", lambda: universe)
    return cov.load_membership_receipt()


def test_generation_is_the_hash_of_the_sorted_positive_expected_set():
    # Expected value computed outside this code base: sha256 of
    # {"expected_netuids":[1..128],"v":1} (sorted keys, compact separators), first 16 hex.
    assert cov.membership_generation(range(1, 129)) == "mg1:2324225a288eb818"
    assert cov.membership_generation([3, 1, 2]) == cov.membership_generation([1, 2, 3])
    assert cov.membership_generation([0, 1, 2, 3]) == cov.membership_generation([1, 2, 3])
    assert cov.membership_generation([1, 2]) != cov.membership_generation([1, 2, 3])


def test_receipt_carries_generation_block_hash_and_rpc_of_the_chain_read(monkeypatch):
    receipt = _receipt_for(monkeypatch, _universe([1, 2, 3], block="cd", rpc="blockmachine"))
    assert receipt["generation"] == cov.membership_generation([1, 2, 3])
    assert receipt["block_hash"] == "0x" + "cd" * 32
    assert receipt["rpc"] == "blockmachine"


def test_generation_moves_at_dereg_not_block_or_grace_expiry(monkeypatch):
    base = _receipt_for(monkeypatch, _universe([1, 2, 77, 78]))["generation"]

    new_block = _receipt_for(monkeypatch, _universe([1, 2, 77, 78], block="ef", rpc="blockmachine"))
    assert new_block["generation"] == base

    # 77 deregisters on chain; its universe row stays for the 48h grace.
    dereg = _receipt_for(monkeypatch, _universe([1, 2, 78], universe_netuids=[1, 2, 77, 78]))
    assert dereg["generation"] != base
    assert 77 not in dereg["expected_netuids"]

    # Grace expires: the row leaves the universe, the chain set is unchanged.
    expired = _receipt_for(monkeypatch, _universe([1, 2, 78]))
    assert expired["generation"] == dereg["generation"]
