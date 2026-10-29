"""A truncated or malformed finalized head must not admit netuids, and a reload must not call it "ok" (#1484 Claude F3).

Claude's probe: a storage layer that answers ``chain_getFinalizedHead`` with ``0x1234`` and echoes that
block on every pinned read. The universe layer parsed that read loosely (``pinned=False``), so the
netuids it listed joined the universe as "degraded"; admission later refused them, but the universe
itself had already accepted them. Main's tests/test_subnet_universe.py pins the registration read with
the literal block "0xabc" through a bare ChainReader double, so the check lives on the real
ChainReader's pin read (which that double replaces), not on ChainRead.parse(pinned=False).

Real ChainReader / read_chain_membership / SnapshotBuilder; only the RPC transport is injected.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from internal import subnet_universe as su
from internal.chain_price import config as chain_cfg
from internal.chain_price.reader import ChainReader

FIXTURE = Path(__file__).parent / "fixtures" / "chain" / "bm_9280796.json"
RECORDED_HEAD = "0x72a82add74d481216a2f4b8f77e7729f88b2abf0654a9c6be89a3cf10f7cedd0"


class _EchoingClient:
    """Replays the recorded membership read but answers the head with ``head`` and echoes it as the block."""

    def __init__(self, head):
        self._head = head
        self._recorded = json.loads(FIXTURE.read_text())

    def _lookup(self, method, params):
        swapped = json.loads(json.dumps(params or []).replace(self._head, RECORDED_HEAD))
        return self._recorded[f"{method}|{json.dumps(swapped)}"]

    def _call_typed(self, method, params=None):
        if method == "chain_getFinalizedHead":
            return self._head
        return self._lookup(method, params)

    def query_storage_at(self, keys, at_hash):
        batch = self._lookup("state_queryStorageAt", [keys, at_hash])
        return [{**entry, "block": at_hash} for entry in batch]


@pytest.fixture
def serve_head(monkeypatch):
    def _serve(head):
        monkeypatch.setattr(chain_cfg, "rpc_provider_clients", lambda: [("finney", _EchoingClient(head))])

    return _serve


def _no_tmc():
    return set(), {}, False


BAD_HEADS = [
    "0x1234",
    "0x" + "ab" * 31,  # 62 hex
    "0x" + "a" * 63,
    "0x" + "a" * 65,
    "0x" + "g" * 64,
    "ab" * 32,  # no 0x
    "0x",
]


def test_control_a_full_64_hex_head_is_read_and_its_netuids_enter(serve_head):
    serve_head(RECORDED_HEAD)
    chain = su._read_chain()
    assert chain is not None and chain.is_pinned
    built = su.SnapshotBuilder(tmc_fetch=_no_tmc).build(None).snapshot
    assert built.chain is not None
    assert set(built.chain.netuids) <= set(built.netuids)


@pytest.mark.parametrize("head", BAD_HEADS)
def test_a_malformed_head_yields_no_chain_read(serve_head, head):
    serve_head(head)
    assert su._read_chain() is None
    observed, complete = su._default_probe_fetch([1, 2, 3])
    assert (observed, complete) == ({}, False)


@pytest.mark.parametrize("head", BAD_HEADS)
def test_a_malformed_head_admits_no_chain_verdict_into_the_universe(serve_head, head):
    serve_head(head)
    built = su.SnapshotBuilder(tmc_fetch=_no_tmc).build(None).snapshot
    assert built.chain is None
    # The chain was the only live source, so only the committed registry fallback remains: nothing
    # is registered on the strength of the malformed read.
    assert built.status == "emergency_registry"
    assert all(entry["sources"] == ["registry"] for entry in built.validity_map.values())


def test_truncated_head_does_not_override_a_prior_universe_with_chain_netuids(serve_head):
    serve_head(RECORDED_HEAD)
    good = su.SnapshotBuilder(tmc_fetch=_no_tmc).build(None).snapshot
    assert good.netuids
    serve_head("0x1234")
    again = su.SnapshotBuilder(tmc_fetch=_no_tmc).build(good).snapshot
    assert again.status != "ok"
    assert again.chain is None or again.chain.block_hash != "0x1234"


def test_the_price_sampler_pin_stays_lenient(serve_head):
    """pin_finalized_head is shared with the price sampler and main's tests (a "0x01" head); only membership is strict."""
    serve_head("0x1234")
    reader = ChainReader([("finney", _EchoingClient("0x1234"))])
    assert reader.pin_finalized_head() == ("0x1234", "ok")
    assert reader.pin_finalized_head_strict() == (None, "invalid")
    assert reader.pinned_hash is None  # a rejected head is not left as the reader's pin


def test_strict_pin_accepts_a_full_head_and_keeps_it_pinned():
    reader = ChainReader([("finney", _EchoingClient(RECORDED_HEAD))])
    assert reader.pin_finalized_head_strict() == (RECORDED_HEAD, "ok")
    assert reader.pinned_hash == RECORDED_HEAD


# --- reload: a snapshot whose chain cannot be re-validated must not come back as "ok" ---


def _payload(chain, *, status="ok", degraded=False):
    return {
        "netuids": [1, 2],
        "rows": [{"netuid": 1}, {"netuid": 2}],
        "resolved_at": "2026-10-29T00:00:00+00:00",
        "status": status,
        "degraded": degraded,
        "validity_map": {},
        "message": "",
        "chain": chain,
    }


@pytest.mark.parametrize(
    "chain",
    [
        {"block_hash": "0x1234", "netuids": [1, 2], "rpc": "finney"},
        {"block_hash": "0x" + "a" * 63, "netuids": [1, 2], "rpc": "finney"},
        None,
        "garbage",
    ],
    ids=["truncated", "63_hex", "missing", "not_a_dict"],
)
def test_reload_without_a_valid_pinned_chain_is_degraded_not_ok(chain):
    snap = su.UniverseSnapshot.from_dict(_payload(chain))
    assert snap.chain is None
    assert snap.status == "degraded"
    assert snap.degraded is True
    assert snap.netuids == (1, 2)  # never blank: the rows survive
    assert snap.message


def test_reload_with_a_valid_pinned_chain_stays_ok():
    chain = {"block_hash": RECORDED_HEAD, "netuids": [1, 2], "rpc": "finney"}
    snap = su.UniverseSnapshot.from_dict(_payload(chain))
    assert (snap.status, snap.degraded) == ("ok", False)
    assert snap.chain.block_hash == RECORDED_HEAD


def test_reload_leaves_other_statuses_alone():
    snap = su.UniverseSnapshot.from_dict(_payload(None, status="emergency_registry", degraded=True))
    assert snap.status == "emergency_registry"


def test_provider_reload_from_disk_reports_the_downgrade(tmp_path):
    path = tmp_path / "universe.json"
    path.write_text(json.dumps(_payload({"block_hash": "0x1234", "netuids": [1, 2], "rpc": "finney"})))
    provider = su.SubnetUniverseProvider(persist_file=str(path))
    assert provider._snapshot.status == "degraded"
    assert provider._snapshot.netuids == (1, 2)
