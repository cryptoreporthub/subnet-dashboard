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


# --- provider fallback: a malformed head from one provider must not hide a valid one (#1484 Replit P2) ---

SECOND_HEAD = RECORDED_HEAD


class _HeadOnlyClient:
    """A provider that answers the finalized head with ``head`` and nothing else."""

    def __init__(self, head):
        self.head = head
        self.calls = []

    def _call_typed(self, method, params=None):
        self.calls.append(method)
        if method == "chain_getFinalizedHead":
            return self.head
        raise RuntimeError("provider cannot serve state")

    def query_storage_at(self, keys, at_hash):
        self.calls.append("state_queryStorageAt")
        raise RuntimeError("provider cannot serve state")


class _RecordingEcho(_EchoingClient):
    def __init__(self, head):
        super().__init__(head)
        self.calls = []

    def _call_typed(self, method, params=None):
        self.calls.append(method)
        return super()._call_typed(method, params)

    def query_storage_at(self, keys, at_hash):
        self.calls.append("state_queryStorageAt")
        return super().query_storage_at(keys, at_hash)


@pytest.mark.parametrize("bad", ["0x1234", "0x" + "a" * 63, "ab" * 32, "0x"])
def test_malformed_head_from_provider_one_falls_back_to_provider_two(monkeypatch, bad):
    first, second = _HeadOnlyClient(bad), _RecordingEcho(RECORDED_HEAD)
    monkeypatch.setattr(chain_cfg, "rpc_provider_clients", lambda: [("finney", first), ("blockmachine", second)])

    chain = su._read_chain()

    assert chain is not None and chain.is_pinned
    assert chain.block_hash == RECORDED_HEAD
    assert chain.rpc == "blockmachine"  # the second provider served the pinned membership read
    assert "state_queryStorageAt" in second.calls
    assert first.calls.count("chain_getFinalizedHead") >= 1


def test_malformed_head_counts_as_a_provider_failure_in_the_reader(monkeypatch):
    first, second = _HeadOnlyClient("0x1234"), _RecordingEcho(RECORDED_HEAD)
    reader = ChainReader([("finney", first), ("blockmachine", second)])

    assert reader.pin_finalized_head_strict() == (RECORDED_HEAD, "ok")
    assert reader.provider_served == "blockmachine"
    assert reader.fallback_count == 1
    assert reader.pinned_hash == RECORDED_HEAD


def test_both_providers_malformed_refuses_the_pin(monkeypatch):
    first, second = _HeadOnlyClient("0x1234"), _HeadOnlyClient("0xabcd")
    monkeypatch.setattr(chain_cfg, "rpc_provider_clients", lambda: [("finney", first), ("blockmachine", second)])

    assert su._read_chain() is None
    reader = ChainReader([("finney", first), ("blockmachine", second)])
    assert reader.pin_finalized_head_strict() == (None, "invalid")
    assert reader.pinned_hash is None
    assert reader.provider_served is None


def test_valid_head_from_provider_one_is_used_without_fallback():
    first, second = _RecordingEcho(RECORDED_HEAD), _HeadOnlyClient("0x1234")
    reader = ChainReader([("finney", first), ("blockmachine", second)])

    assert reader.pin_finalized_head_strict() == (RECORDED_HEAD, "ok")
    assert reader.provider_served == "finney"
    assert second.calls == []


def test_the_lenient_pin_still_accepts_provider_ones_short_head_without_fallback():
    """The sampler's pin and main's tests ("0x01") must not start falling back."""
    first, second = _HeadOnlyClient("0x01"), _RecordingEcho(RECORDED_HEAD)
    reader = ChainReader([("finney", first), ("blockmachine", second)])

    assert reader.pin_finalized_head() == ("0x01", "ok")
    assert reader.provider_served == "finney"
    assert second.calls == []
    # and the strict flag does not leak into later lenient calls
    reader.pin_finalized_head_strict()
    assert reader._strict_pin is False
    assert reader.pin_finalized_head() == ("0x01", "ok")


# --- the strict flag is per thread: a shared reader's other callers keep the lenient pin (#1484 Replit) ---


def test_strict_pin_does_not_leak_into_a_concurrent_lenient_pin_on_a_shared_reader():
    import threading

    in_strict_call = threading.Event()
    release = threading.Event()
    strict_thread = {}

    class _Client:
        def _call_typed(self, method, params=None):
            if method == "chain_getFinalizedHead" and threading.current_thread() is strict_thread["t"]:
                in_strict_call.set()
                assert release.wait(10)
            return "0x01"

    reader = ChainReader([("finney", _Client())])
    results = {}

    def strict():
        results["strict"] = reader.pin_finalized_head_strict()

    strict_thread["t"] = threading.Thread(target=strict)
    strict_thread["t"].start()
    assert in_strict_call.wait(10)
    try:
        results["lenient"] = reader.pin_finalized_head()  # runs while the strict call is in flight
    finally:
        release.set()
        strict_thread["t"].join(10)

    assert results["lenient"] == ("0x01", "ok")  # not rejected by the other thread's strict mode
    assert results["strict"] == (None, "invalid")  # the strict caller still is
    assert reader._strict_pin is False


# --- every membership read follows the provider that served the accepted head (#1484 Claude 1) ---


class _DecoyClient(_HeadOnlyClient):
    """Malformed head, but it would happily answer state reads (keys carry no block echo)."""

    def _call_typed(self, method, params=None):
        self.calls.append(method)
        if method == "chain_getFinalizedHead":
            return self.head
        if method == "state_getKeysPaged":
            return ["0x" + "00" * 32]  # a decoy key list nobody vouched for
        raise RuntimeError("no")

    def query_storage_at(self, keys, at_hash):
        self.calls.append("state_queryStorageAt")
        raise RuntimeError("no")


def test_state_reads_never_touch_the_provider_whose_head_was_malformed(monkeypatch):
    first, second = _DecoyClient("0x1234"), _RecordingEcho(RECORDED_HEAD)
    monkeypatch.setattr(chain_cfg, "rpc_provider_clients", lambda: [("finney", first), ("blockmachine", second)])

    chain = su._read_chain()

    assert chain is not None and chain.rpc == "blockmachine"
    assert set(first.calls) == {"chain_getFinalizedHead"}  # asked for the head only, never for keys or values
    assert {"state_getKeysPaged", "state_queryStorageAt"} <= set(second.calls)
    assert len(chain.netuids) > 1  # the decoy key list did not replace the recorded one


def test_pinned_reads_do_not_fall_back_to_another_provider():
    first, second = _RecordingEcho(RECORDED_HEAD), _RecordingEcho(RECORDED_HEAD)
    reader = ChainReader([("finney", first), ("blockmachine", second)])
    assert reader.pin_finalized_head_strict() == (RECORDED_HEAD, "ok")
    first.query_storage_at = lambda keys, at_hash: (_ for _ in ()).throw(RuntimeError("down"))

    _, outcome = reader.pinned_call_fn()("state_queryStorageAt", [["0x00"], RECORDED_HEAD])

    assert outcome == "rpc_error"  # reported as is: blockmachine is not consulted
    assert "state_queryStorageAt" not in second.calls


def test_refused_strict_pin_clears_a_provider_label_left_by_an_earlier_read():
    first = _HeadOnlyClient("0x01")
    reader = ChainReader([("finney", first)])
    assert reader.pin_finalized_head() == ("0x01", "ok")  # an earlier lenient read: finney served
    assert reader.provider_served == "finney"

    assert reader.pin_finalized_head_strict() == (None, "invalid")

    assert reader.provider_served is None
    assert reader.pinned_hash is None


# --- a shared reader never pairs one provider's head with another provider's keys (#1484 Claude r8 / Ditto r8) ---


def _shared_reader_with_other_thread_lenient_pin(first, second):
    """A reader whose strict pin is served by provider two; just before the membership reads bind to
    a provider, ANOTHER thread's lenient pin succeeds on provider one (rewriting ``provider_served``)."""
    import threading

    class _Racy(ChainReader):
        interleaved = False

        def pinned_call_fn(self):
            def other_thread():
                assert self.pin_finalized_head()[1] == "ok"  # lenient: provider one's short head is accepted

            t = threading.Thread(target=other_thread)
            t.start()
            t.join(10)
            type(self).interleaved = True
            assert self.provider_served == "finney"  # the schedule really did overwrite the shared label
            return super().pinned_call_fn()

    return _Racy([("finney", first), ("blockmachine", second)])


def test_shared_reader_membership_reads_stay_on_the_provider_that_served_the_head():
    from internal.chain_price.membership import read_chain_membership

    first, second = _DecoyClient("0x1234"), _RecordingEcho(RECORDED_HEAD)
    reader = _shared_reader_with_other_thread_lenient_pin(first, second)

    chain, outcome = read_chain_membership(reader)

    assert type(reader).interleaved
    assert outcome == "ok" and chain is not None
    assert chain.rpc == "blockmachine"  # the receipt names the provider that served the accepted head
    assert chain.block_hash == RECORDED_HEAD
    assert set(first.calls) == {"chain_getFinalizedHead"}  # provider one (malformed head) served no keys or values
    assert {"state_getKeysPaged", "state_queryStorageAt"} <= set(second.calls)
    assert len(chain.netuids) > 1  # not the decoy key list


def test_head_provider_is_per_thread_and_survives_another_threads_call():
    import threading

    first, second = _RecordingEcho(RECORDED_HEAD), _RecordingEcho(RECORDED_HEAD)
    reader = ChainReader([("finney", first), ("blockmachine", second)])
    reader._providers = reader._providers[::-1]  # blockmachine first: it serves the strict head
    assert reader.pin_finalized_head_strict() == (RECORDED_HEAD, "ok")
    assert reader.head_provider == "blockmachine"

    seen = {}

    def other():
        reader._providers = reader._providers[::-1]  # finney first for the other caller
        reader.pin_finalized_head()
        seen["other_head"] = reader.head_provider  # a thread that never strict-pinned has no capture

    t = threading.Thread(target=other)
    t.start()
    t.join(10)

    assert reader.provider_served == "finney"  # the shared diagnostic label moved
    assert reader.head_provider == "blockmachine"  # this thread's head did not
    assert seen["other_head"] is None
    reader.reset_pin()
    assert reader.head_provider is None
