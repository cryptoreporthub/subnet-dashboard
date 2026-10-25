"""Membership provenance on score snapshots (#1479 PR-B, act-on 1).

Real SnapshotBuilder / _read_chain / ChainReader code; only the RPC transport and the
TMC fetch are injected, replaying a recorded chain read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from internal.chain_price import config as chain_cfg
from internal.chain_read import ChainRead
from internal import subnet_universe as su

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
