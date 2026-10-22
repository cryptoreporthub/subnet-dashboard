import os
import time
from unittest.mock import MagicMock, patch

import pytest

from internal.chain_rpc_errors import ChainRpcError
from internal.chain_price.storage_keys import map_key_hex

VALID_PINNED_HASH = "0x" + "ab" * 32


def _fetch_snapshot_batch(monkeypatch, universe, *, deadline=None):
    from internal.chain_price.live_subnet_snapshot import fetch_live_subnet_snapshot

    if deadline is not None:
        monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_MONOTONIC", str(deadline))
        end = float(deadline)
    else:
        env_dead = os.environ.get("LIVE_SUBNETS_BATCH_DEADLINE_MONOTONIC", "").strip()
        if env_dead:
            end = float(env_dead)
        else:
            monkeypatch.delenv("LIVE_SUBNETS_BATCH_DEADLINE_MONOTONIC", raising=False)
            budget = float(os.environ.get("LIVE_SUBNETS_BATCH_DEADLINE_SECONDS", "85"))
            monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_SECONDS", str(budget))
            end = time.monotonic() + budget
    snap = fetch_live_subnet_snapshot(end)
    outcomes = dict(snap.netuid_outcomes)
    membership_resolved = snap.membership_resolved if hasattr(snap, "membership_resolved") else True
    failure = snap.failure if hasattr(snap, "failure") else None
    if membership_resolved:
        member_set = set(snap.requested_netuids)
        for n in sorted({int(x) for x in universe}):
            if n not in member_set:
                outcomes[int(n)] = "not_member"
    return {
        "rows": list(snap.rows),
        "batch_expired": snap.batch_expired,
        "netuid_outcomes": outcomes,
        "membership_resolved": membership_resolved,
        "failure": failure,
        "snapshot": snap,
    }


def _u64_storage_hex(value: int) -> str:
    return "0x" + int(value).to_bytes(8, "little").hex()


def _install_storage_batch_rpc_mock(monkeypatch, members, reserve_by_netuid, *, rpc_calls=None):
    """Patch ChainReader for batched snapshot tests (Finney-first path)."""
    if rpc_calls is None:
        rpc_calls = []

    def fake_pin(self):
        self.provider_served = "finney"
        return VALID_PINNED_HASH, "ok"

    def fake_call(self, method, params):
        rpc_calls.append(method)
        if method == "chain_getFinalizedHead":
            return VALID_PINNED_HASH, "ok"
        if method == "state_queryStorageAt":
            keys, _block_hash = params
            changes = []
            for key in keys:
                for netuid, reserves in reserve_by_netuid.items():
                    tao_key = map_key_hex(b"SubnetTAO", netuid)
                    alpha_key = map_key_hex(b"SubnetAlphaIn", netuid)
                    if key == tao_key:
                        changes.append([key, _u64_storage_hex(reserves[0])])
                    elif key == alpha_key:
                        changes.append([key, _u64_storage_hex(reserves[1])])
            return [{"block": VALID_PINNED_HASH, "changes": changes}], "ok"
        return None, "rpc_error"

    member_fn = lambda _call, _at_hash: (list(members), "ok")
    monkeypatch.setattr("internal.chain_price.membership.get_member_netuids", member_fn)
    monkeypatch.setattr("internal.chain_price.live_subnet_snapshot.get_member_netuids", member_fn)
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.pin_finalized_head", fake_pin)
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.call", fake_call)
    return rpc_calls


@pytest.fixture
def clear_endpoint_rate_limits():
    from internal.chain_client import _RL_LOCK, _RL_STEP, _RL_UNTIL

    with _RL_LOCK:
        _RL_UNTIL.clear()
        _RL_STEP.clear()
    yield
    with _RL_LOCK:
        _RL_UNTIL.clear()
        _RL_STEP.clear()



def test_clamp_client_rpc_timeout_respects_floor_and_original():
    import time

    from internal.chain_client import ChainClient, clamp_client_rpc_timeout

    client = ChainClient("https://clamp.example", timeout=30.0, init_volume_db=False, retries=0)
    originals: dict = {}
    clamp_client_rpc_timeout(client, time.monotonic() + 0.001, originals)
    assert client.timeout == 0.01

    client2 = ChainClient("https://clamp2.example", timeout=4.0, init_volume_db=False, retries=0)
    originals2: dict = {}
    clamp_client_rpc_timeout(client2, time.monotonic() + 100.0, originals2)
    assert client2.timeout == 4.0



def test_cooldown_skip_classification_uses_local_exception_not_wire_code():
    from internal.chain_client import _classify_alpha_price_probe_error
    from internal.chain_rpc_errors import ChainRpcError, EndpointRpcCooldownActive

    assert _classify_alpha_price_probe_error(EndpointRpcCooldownActive()) == "cooldown_skip"
    wire = ChainRpcError("rate_limited", "server", code=-32098)
    assert _classify_alpha_price_probe_error(wire) != "cooldown_skip"


def test_shared_endpoint_cooldown_blocks_second_client(clear_endpoint_rate_limits):
    from internal.chain_client import ChainClient

    endpoint = "https://rpc.shared.example"
    first = ChainClient(endpoint, init_volume_db=False, retries=0)
    second = ChainClient(endpoint, init_volume_db=False, retries=0)
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {}
    with patch("internal.chain_client.requests.post", return_value=resp) as post:
        with pytest.raises(ChainRpcError) as exc:
            first._call_typed("chain_getBlockHash", [])
        assert exc.value.kind == "rate_limited"
        assert post.call_count == 1
        from internal.chain_rpc_errors import EndpointRpcCooldownActive

        with pytest.raises(EndpointRpcCooldownActive):
            second._call_typed("chain_getBlockHash", [])
        assert post.call_count == 1


def test_endpoint_cooldown_does_not_block_other_endpoints(clear_endpoint_rate_limits):
    from internal.chain_client import ChainClient

    a = ChainClient("https://rpc.a.example", init_volume_db=False, retries=0)
    b = ChainClient("https://rpc.b.example", init_volume_db=False, retries=0)
    bad = MagicMock()
    bad.status_code = 429
    bad.headers = {}
    good = MagicMock()
    good.status_code = 200
    good.json.return_value = {"result": "0x01"}
    good.raise_for_status = MagicMock()
    with patch("internal.chain_client.requests.post", side_effect=[bad, good]) as post:
        with pytest.raises(ChainRpcError):
            a._call_typed("chain_getBlockHash", [])
        assert b._call_typed("chain_getBlockHash", []) == "0x01"
        assert post.call_count == 2


def test_retry_after_honored_on_429(clear_endpoint_rate_limits):
    from internal.chain_client import ChainClient, rate_limited_until

    client = ChainClient("https://rpc.retry.example", init_volume_db=False, retries=0)
    clock = [100.0]
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {"Retry-After": "120"}
    with patch("internal.chain_client.time.monotonic", side_effect=lambda: clock[0]):
        with patch("internal.chain_client.requests.post", return_value=resp):
            with pytest.raises(ChainRpcError):
                client._call_typed("chain_getBlockHash", [])
        assert rate_limited_until(client.endpoint) == 220.0


def test_traffic_resumes_after_cooldown_expires(clear_endpoint_rate_limits):
    from internal.chain_client import ChainClient, note_rate_limit

    client = ChainClient("https://rpc.resume.example", init_volume_db=False, retries=0)
    clock = [0.0]
    with patch("internal.chain_client.time.monotonic", side_effect=lambda: clock[0]):
        note_rate_limit(client.endpoint, 5.0)
        clock[0] = 4.9
        from internal.chain_rpc_errors import EndpointRpcCooldownActive

        with pytest.raises(EndpointRpcCooldownActive):
            client._call_typed("chain_getBlockHash", [])
        clock[0] = 5.1
        good = MagicMock()
        good.status_code = 200
        good.json.return_value = {"result": "0xab"}
        good.raise_for_status = MagicMock()
        with patch("internal.chain_client.requests.post", return_value=good) as post:
            assert client._call_typed("chain_getBlockHash", []) == "0xab"
            assert post.call_count == 1


def test_burst_note_rate_limit_single_escalation(clear_endpoint_rate_limits):
    from internal.chain_client import _RL_LOCK, _RL_STEP, _RL_UNTIL, note_rate_limit

    ep = "https://burst.example"
    clock = [0.0]
    with patch("internal.chain_client.time.monotonic", side_effect=lambda: clock[0]):
        for _ in range(5):
            note_rate_limit(ep)
    norm = ep.rstrip("/")
    assert _RL_STEP[norm] == 120.0
    assert _RL_UNTIL[norm] == 60.0


def test_shorter_retry_after_does_not_shorten_active_cooldown(clear_endpoint_rate_limits):
    from internal.chain_client import note_rate_limit, rate_limited_until

    ep = "https://x.example"
    clock = [0.0]
    with patch("internal.chain_client.time.monotonic", side_effect=lambda: clock[0]):
        note_rate_limit(ep, 600.0)
        until_long = rate_limited_until(ep)
        note_rate_limit(ep, 5.0)
        assert rate_limited_until(ep) == until_long


def test_reader_retry_after_600_with_real_client(clear_endpoint_rate_limits):
    from internal.chain_client import ChainClient, rate_limited_until
    from internal.chain_price.reader import ChainReader

    client = ChainClient("https://finney.example", init_volume_db=False, retries=0)
    reader = ChainReader([("finney", client)])
    clock = [1000.0]
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {"Retry-After": "600"}
    mono = lambda: clock[0]
    with patch("internal.chain_client.time.monotonic", side_effect=mono), patch(
        "internal.chain_price.reader.time.monotonic", side_effect=mono
    ):
        with patch("internal.chain_client.requests.post", return_value=resp):
            _, outcome = reader.call("chain_getFinalizedHead", [])
        assert outcome == "rate_limited"
        assert rate_limited_until(client.endpoint) - clock[0] >= 600.0


def test_parse_retry_after_http_date_future(clear_endpoint_rate_limits):
    from datetime import datetime, timezone

    from internal.chain_client import _parse_retry_after_header

    wall = 1_700_000_000.0
    future = datetime.fromtimestamp(wall + 600, tz=timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )
    resp = MagicMock()
    resp.headers = {"Retry-After": future}
    with patch("internal.chain_client.time.time", return_value=wall):
        assert _parse_retry_after_header(resp) == 600.0


def test_parse_retry_after_http_date_past(clear_endpoint_rate_limits):
    from datetime import datetime, timezone

    from internal.chain_client import _parse_retry_after_header

    wall = 1_700_000_000.0
    past = datetime.fromtimestamp(wall - 120, tz=timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )
    resp = MagicMock()
    resp.headers = {"Retry-After": past}
    with patch("internal.chain_client.time.time", return_value=wall):
        assert _parse_retry_after_header(resp) == 0.0


def test_reader_retry_after_http_date_with_real_client(clear_endpoint_rate_limits):
    from datetime import datetime, timezone

    from internal.chain_client import ChainClient, rate_limited_until
    from internal.chain_price.reader import ChainReader

    client = ChainClient("https://finney-date.example", init_volume_db=False, retries=0)
    reader = ChainReader([("finney", client)])
    wall = 1_700_000_000.0
    mono = 5000.0
    future = datetime.fromtimestamp(wall + 600, tz=timezone.utc).strftime(
        "%a, %d %b %Y %H:%M:%S GMT"
    )
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {"Retry-After": future}
    with patch("internal.chain_client.time.time", return_value=wall), patch(
        "internal.chain_client.time.monotonic", return_value=mono
    ), patch("internal.chain_price.reader.time.monotonic", return_value=mono):
        with patch("internal.chain_client.requests.post", return_value=resp):
            _, outcome = reader.call("chain_getFinalizedHead", [])
        assert outcome == "rate_limited"
        assert rate_limited_until(client.endpoint) - mono >= 600.0


def test_chain_rpc_requests_total_increments(clear_endpoint_rate_limits):
    from internal.chain_client import ChainClient
    from internal.metrics import CHAIN_RPC_REQUESTS_TOTAL

    client = ChainClient("https://rpc.metrics.example", init_volume_db=False, retries=0)
    endpoint = "rpc.metrics.example"
    before_ok = CHAIN_RPC_REQUESTS_TOTAL.labels(
        endpoint=endpoint, method="chain_getBlockHash", outcome="ok"
    )._value.get()
    before_rl = CHAIN_RPC_REQUESTS_TOTAL.labels(
        endpoint=endpoint, method="chain_getBlockHash", outcome="rate_limited"
    )._value.get()
    before_skip = CHAIN_RPC_REQUESTS_TOTAL.labels(
        endpoint=endpoint, method="chain_getBlockHash", outcome="cooldown_skip"
    )._value.get()
    good = MagicMock()
    good.status_code = 200
    good.json.return_value = {"result": "0x01"}
    good.raise_for_status = MagicMock()
    clock = [50.0]
    with patch("internal.chain_client.time.monotonic", side_effect=lambda: clock[0]):
        with patch("internal.chain_client.requests.post", return_value=good):
            client._call_typed("chain_getBlockHash", [])
        assert (
            CHAIN_RPC_REQUESTS_TOTAL.labels(
                endpoint=endpoint, method="chain_getBlockHash", outcome="ok"
            )._value.get()
            == before_ok + 1
        )
        resp429 = MagicMock()
        resp429.status_code = 429
        resp429.headers = {}
        with patch("internal.chain_client.requests.post", return_value=resp429):
            with pytest.raises(ChainRpcError):
                client._call_typed("chain_getBlockHash", [])
        with pytest.raises(ChainRpcError):
            client._call_typed("chain_getBlockHash", [])
    assert (
        CHAIN_RPC_REQUESTS_TOTAL.labels(
            endpoint=endpoint, method="chain_getBlockHash", outcome="rate_limited"
        )._value.get()
        == before_rl + 1
    )
    assert (
        CHAIN_RPC_REQUESTS_TOTAL.labels(
            endpoint=endpoint, method="chain_getBlockHash", outcome="cooldown_skip"
        )._value.get()
        == before_skip + 1
    )


@pytest.mark.parametrize("call_name", ["_call", "_call_typed"])
def test_http_429_sets_transport_http_status(clear_endpoint_rate_limits, call_name):
    from internal.chain_client import ChainClient

    client = ChainClient("https://rpc.http429.example", init_volume_db=False, retries=0)
    resp429 = MagicMock()
    resp429.status_code = 429
    resp429.headers = {}
    with patch("internal.chain_client.requests.post", return_value=resp429):
        with pytest.raises(ChainRpcError) as exc_info:
            getattr(client, call_name)("chain_getBlockHash", [])
    assert exc_info.value.kind == "rate_limited"
    assert exc_info.value.http_status == 429


def test_price_batch_deadline_returns_completed_rows(monkeypatch):
    from internal.chain_client import ChainClient

    client = ChainClient()
    _install_storage_batch_rpc_mock(
        monkeypatch,
        members=[1, 2],
        reserve_by_netuid={1: (1_000_000_000, 1_000_000_000), 2: (2_000_000_000, 1_000_000_000)},
    )
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_SECONDS", "85")
    rows = _fetch_snapshot_batch(monkeypatch, [2, 1])["rows"]
    assert [r["netuid"] for r in rows] == [1, 2]
    assert rows[0]["source"] == "finney"


def _deadline_after_first_storage_mock(monkeypatch, members, reserve_by_netuid, deadline: float):
    clock = [time.monotonic()]

    def fake_pin(self):
        self.provider_served = "finney"
        return VALID_PINNED_HASH, "ok"

    storage_calls = [0]

    def fake_call(self, method, params):
        if method == "state_queryStorageAt":
            storage_calls[0] += 1
            if storage_calls[0] >= 1:
                clock[0] = deadline + 0.01
            keys, _block_hash = params
            changes = []
            for key in keys:
                for netuid, reserves in reserve_by_netuid.items():
                    tao_key = map_key_hex(b"SubnetTAO", netuid)
                    alpha_key = map_key_hex(b"SubnetAlphaIn", netuid)
                    if key == tao_key:
                        changes.append([key, _u64_storage_hex(reserves[0])])
                    elif key == alpha_key:
                        changes.append([key, _u64_storage_hex(reserves[1])])
            return [{"block": VALID_PINNED_HASH, "changes": changes}], "ok"
        if method == "chain_getFinalizedHead":
            return VALID_PINNED_HASH, "ok"
        return None, "rpc_error"

    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    member_fn = lambda _call, _at_hash: (list(members), "ok")
    monkeypatch.setattr("internal.chain_price.membership.get_member_netuids", member_fn)
    monkeypatch.setattr("internal.chain_price.live_subnet_snapshot.get_member_netuids", member_fn)
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.pin_finalized_head", fake_pin)
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.call", fake_call)


def test_batch_deadline_honors_parent_monotonic_deadline(monkeypatch):
    from internal.chain_client import ChainClient

    client = ChainClient()
    deadline = time.monotonic() + 0.1
    _deadline_after_first_storage_mock(
        monkeypatch,
        members=[1, 2],
        reserve_by_netuid={1: (1_000_000_000, 1_000_000_000), 2: (2_000_000_000, 1_000_000_000)},
        deadline=deadline,
    )
    monkeypatch.setattr("internal.chain_price.live_subnet_snapshot._STORAGE_CHUNK_NETUIDS", 1)
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_MONOTONIC", str(deadline))
    batch = _fetch_snapshot_batch(monkeypatch, [2, 1], deadline=deadline)
    assert batch["batch_expired"] is True
    assert batch["netuid_outcomes"].get(2) == "batch_expired"


def test_storage_batch_128_netuids_constant_rpc_count(monkeypatch):
    from internal.chain_client import ChainClient

    client = ChainClient()
    members = list(range(1, 129))
    reserves = {n: (n * 1_000_000_000, 1_000_000_000) for n in members}
    rpc_calls = _install_storage_batch_rpc_mock(monkeypatch, members, reserves)
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_SECONDS", "85")

    batch_128 = _fetch_snapshot_batch(monkeypatch, members)
    count_128 = len(rpc_calls)
    assert len(batch_128["rows"]) == 128

    rpc_calls.clear()
    batch_hint = _fetch_snapshot_batch(monkeypatch, members[:10] + [200])
    count_hint = len(rpc_calls)
    assert len(batch_hint["rows"]) == 128
    assert batch_hint["netuid_outcomes"].get(200) == "not_member"
    assert count_128 == count_hint
    assert count_128 <= 4


def test_price_batch_no_price_is_fetch_errors_not_batch_deadline(monkeypatch):
    from internal.chain_client import ChainClient

    client = ChainClient()
    _install_storage_batch_rpc_mock(
        monkeypatch,
        members=[1],
        reserve_by_netuid={1: (1_000_000_000, 1_000_000_000)},
    )
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_SECONDS", "2")
    batch = _fetch_snapshot_batch(monkeypatch,[1, 2])
    assert batch["batch_expired"] is False
    assert batch["netuid_outcomes"][2] == "not_member"
    from internal.live_subnets_fetch_child import fetch_meta_from_batch

    meta = fetch_meta_from_batch(
        [1],
        batch["rows"],
        batch_expired=batch["batch_expired"],
        netuid_outcomes=batch["netuid_outcomes"],
    )
    assert meta["refresh_complete"] is True
    assert meta["degraded_reason"] is None


def test_get_alpha_price_probed_null_vs_rpc_error(monkeypatch):
    from internal.chain_client import ChainClient

    client = ChainClient.__new__(ChainClient)

    def call(method, params):
        if params == [2]:
            raise TimeoutError("rpc timeout")
        if params == [3]:
            return None
        return 1_000_000_000

    client._call = call
    price_ok, outcome_ok = client.get_alpha_price_probed(1)
    assert outcome_ok == "ok"
    assert price_ok == 1.0
    price_err, outcome_err = client.get_alpha_price_probed(2)
    assert outcome_err == "timeout"
    assert price_err is None
    price_none, outcome_none = client.get_alpha_price_probed(3)
    assert outcome_none == "no_price"
    assert price_none is None
    assert client.get_alpha_price(2) is None
    assert client.get_alpha_price(3) is None


def test_price_batch_storage_rpc_error_is_fetch_errors_not_batch_deadline(monkeypatch):
    from internal.chain_client import ChainClient

    client = ChainClient()

    def fake_pin(self):
        self.provider_served = "finney"
        return VALID_PINNED_HASH, "ok"

    def fake_call(self, method, params):
        if method == "state_queryStorageAt":
            return None, "timeout"
        if method == "chain_getFinalizedHead":
            return VALID_PINNED_HASH, "ok"
        return None, "rpc_error"

    member_fn = lambda _call, _at_hash: ([1, 2], "ok")
    monkeypatch.setattr("internal.chain_price.membership.get_member_netuids", member_fn)
    monkeypatch.setattr("internal.chain_price.live_subnet_snapshot.get_member_netuids", member_fn)
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.pin_finalized_head", fake_pin)
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.call", fake_call)
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_SECONDS", "2")
    batch = _fetch_snapshot_batch(monkeypatch,[1, 2])
    assert batch["batch_expired"] is False
    assert batch["netuid_outcomes"][1] == "timeout"
    assert batch["netuid_outcomes"][2] == "timeout"
    from internal.live_subnets_fetch_child import fetch_meta_from_batch

    meta = fetch_meta_from_batch(
        [1, 2],
        batch["rows"],
        batch_expired=batch["batch_expired"],
        netuid_outcomes=batch["netuid_outcomes"],
    )
    assert meta["degraded_reason"] == "fetch_errors"


def test_price_batch_deadline_partial_sets_batch_expired(monkeypatch):
    from internal.chain_client import ChainClient

    client = ChainClient()
    deadline = time.monotonic() + 0.1
    _deadline_after_first_storage_mock(
        monkeypatch,
        members=[1, 2],
        reserve_by_netuid={1: (1_000_000_000, 1_000_000_000), 2: (2_000_000_000, 1_000_000_000)},
        deadline=deadline,
    )
    monkeypatch.setattr("internal.chain_price.live_subnet_snapshot._STORAGE_CHUNK_NETUIDS", 1)
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_MONOTONIC", str(deadline))
    batch = _fetch_snapshot_batch(monkeypatch, [2, 1], deadline=deadline)
    assert batch["batch_expired"] is True
    assert batch["netuid_outcomes"].get(2) == "batch_expired"
    from internal.live_subnets_fetch_child import fetch_meta_from_batch

    meta = fetch_meta_from_batch(
        [2, 1],
        batch["rows"],
        batch_expired=batch["batch_expired"],
        netuid_outcomes=batch["netuid_outcomes"],
    )
    assert meta["degraded_reason"] == "batch_deadline"


def test_storage_batch_deadline_partial_refresh_meta(monkeypatch):
    members = list(range(1, 131))
    reserves = {n: (n * 1_000_000_000, 1_000_000_000) for n in members}
    deadline = time.monotonic() + 10.0
    storage_calls = [0]

    def fake_pin(self):
        self.provider_served = "finney"
        return VALID_PINNED_HASH, "ok"

    def fake_call(self, method, params):
        if method == "state_queryStorageAt":
            storage_calls[0] += 1
            if storage_calls[0] >= 2:
                return None, "rpc_error"
            keys, _block_hash = params
            changes = []
            for key in keys:
                for netuid, pair in reserves.items():
                    if key == map_key_hex(b"SubnetTAO", netuid):
                        changes.append([key, _u64_storage_hex(pair[0])])
                    elif key == map_key_hex(b"SubnetAlphaIn", netuid):
                        changes.append([key, _u64_storage_hex(pair[1])])
            return [{"block": VALID_PINNED_HASH, "changes": changes}], "ok"
        if method == "chain_getFinalizedHead":
            return VALID_PINNED_HASH, "ok"
        return None, "rpc_error"

    member_fn = lambda _call, _at_hash: (members, "ok")
    monkeypatch.setattr("internal.chain_price.membership.get_member_netuids", member_fn)
    monkeypatch.setattr("internal.chain_price.live_subnet_snapshot.get_member_netuids", member_fn)
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.pin_finalized_head", fake_pin)
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.call", fake_call)
    clock = [time.monotonic()]

    def fake_call_deadline(self, method, params):
        if method == "state_queryStorageAt":
            keys, _ = params
            if map_key_hex(b"SubnetTAO", 129) in keys:
                clock[0] = deadline + 0.01
        return fake_call(self, method, params)

    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.call", fake_call_deadline)
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_MONOTONIC", str(deadline))
    batch = _fetch_snapshot_batch(monkeypatch, members, deadline=deadline)
    from internal.live_subnets_fetch_child import fetch_meta_from_batch

    meta = fetch_meta_from_batch(
        members,
        batch["rows"],
        batch_expired=batch["batch_expired"],
        netuid_outcomes=batch["netuid_outcomes"],
    )
    assert meta["refresh_complete"] is False
    assert sorted(meta["missing_netuids"]) == [129, 130]


def test_batched_reserve_price_matches_swap_fixture():
    import json
    from pathlib import Path

    from internal.chain_client import PRICE_SCALE, _row_from_subnet_reserves

    fixture = json.loads(
        Path("tests/fixtures/live_subnet_reserve_parity.json").read_text(encoding="utf-8")
    )
    row = _row_from_subnet_reserves(
        int(fixture["netuid"]),
        int(fixture["tao_raw"]),
        int(fixture["alpha_raw"]),
        "finney",
    )
    swap_price = int(fixture["swap_scaled"]) / PRICE_SCALE
    rel = abs(swap_price - row["price"]) / swap_price
    assert rel < 1e-4


def test_snapshot_membership_request_ignores_inactive_universe_slots(monkeypatch):
    from internal.chain_client import ChainClient

    members = list(range(1, 129))
    reserves = {n: (n * 1_000_000_000, 1_000_000_000) for n in members}
    _install_storage_batch_rpc_mock(monkeypatch, members, reserves)
    client = ChainClient()
    universe = members + [200, 201]
    batch = _fetch_snapshot_batch(monkeypatch,universe)
    assert batch["netuid_outcomes"].get(200) == "not_member"
    assert batch["netuid_outcomes"].get(201) == "not_member"
    assert len(batch["rows"]) == 128
    assert all(batch["netuid_outcomes"].get(n) == "ok" for n in members)


def test_classify_alpha_price_probe_requests_exceptions():
    import requests

    from internal.chain_client import _classify_alpha_price_probe_error

    assert _classify_alpha_price_probe_error(requests.exceptions.ReadTimeout()) == "timeout"
    assert _classify_alpha_price_probe_error(requests.exceptions.ConnectionError()) == "connection"
    assert (
        _classify_alpha_price_probe_error(
            requests.exceptions.HTTPError(response=type("R", (), {"status_code": 429})())
        )
        == "rate_limited"
    )


def test_price_chunk_provider_follows_fallback(monkeypatch):
    from internal.chain_client import ChainClient

    client = ChainClient()
    member_fn = lambda _call, _at_hash: ([1], "ok")
    monkeypatch.setattr("internal.chain_price.membership.get_member_netuids", member_fn)
    monkeypatch.setattr("internal.chain_price.live_subnet_snapshot.get_member_netuids", member_fn)

    class _Reader:
        def __init__(self, _clients=None):
            self.provider_served = "finney"
            self._providers = []

        def call_fn(self):
            def _call(method, params):
                if method != "state_queryStorageAt":
                    return VALID_PINNED_HASH, "ok"
                keys, _block_hash = params
                tao_key = map_key_hex(b"SubnetTAO", 1)
                if tao_key not in keys:
                    return [{"block": VALID_PINNED_HASH, "changes": [[keys[0], "0x01"]]}], "ok"
                self.provider_served = "blockmachine"
                alpha_key = map_key_hex(b"SubnetAlphaIn", 1)
                changes = [
                    [tao_key, _u64_storage_hex(1_000_000_000)],
                    [alpha_key, _u64_storage_hex(1_000_000_000)],
                ]
                return [{"block": VALID_PINNED_HASH, "changes": changes}], "ok"

            return _call

        def pin_finalized_head(self):
            self.provider_served = "finney"
            return VALID_PINNED_HASH, "ok"

        def reset_pin(self):
            pass

    monkeypatch.setattr("internal.chain_price.live_subnet_snapshot.ChainReader", _Reader)
    batch = _fetch_snapshot_batch(monkeypatch, [1])
    assert batch["rows"][0]["source"] == "blockmachine"


def test_snapshot_membership_rpc_error_not_not_member(monkeypatch):
    import json

    from internal.live_subnets_fetch_child import collect_chain_rows

    monkeypatch.setenv("LIVE_SUBNETS_TEST_REQUESTED_NETUIDS", json.dumps(list(range(1, 166))))

    def fail_members(_call, _at_hash):
        return [], "rpc_error"

    monkeypatch.setattr("internal.chain_price.membership.get_member_netuids", fail_members)
    monkeypatch.setattr("internal.chain_price.live_subnet_snapshot.get_member_netuids", fail_members)
    rows, _active, meta = collect_chain_rows()
    assert rows == []
    assert meta["refresh_complete"] is False
    assert meta["degraded_reason"] == "membership:rpc_error"
    assert "not_member" not in meta.get("netuid_outcomes", {}).values()


def test_snapshot_slow_head_pin_hits_deadline(monkeypatch):
    deadline = time.monotonic() + 0.05
    clock = [time.monotonic()]

    def slow_pin(self):
        clock[0] = deadline + 0.01
        self.provider_served = "finney"
        return VALID_PINNED_HASH, "ok"

    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.pin_finalized_head", slow_pin)
    batch = _fetch_snapshot_batch(monkeypatch, [1], deadline=deadline)
    assert batch["membership_resolved"] is False
    assert batch["failure"] == "membership:deadline"


def test_snapshot_slow_membership_hits_deadline(monkeypatch):
    deadline = time.monotonic() + 0.05
    clock = [time.monotonic()]

    def fake_pin(self):
        self.provider_served = "finney"
        return VALID_PINNED_HASH, "ok"

    def slow_members(_call, _at_hash):
        clock[0] = deadline + 0.01
        return list(range(1, 5)), "ok"

    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.pin_finalized_head", fake_pin)
    monkeypatch.setattr("internal.chain_price.membership.get_member_netuids", slow_members)
    monkeypatch.setattr("internal.chain_price.live_subnet_snapshot.get_member_netuids", slow_members)
    batch = _fetch_snapshot_batch(monkeypatch, [1, 2, 3, 4], deadline=deadline)
    assert batch["membership_resolved"] is False
    assert batch["failure"] == "membership:deadline"


def test_finney_empty_finalized_head_falls_back_to_blockmachine():
    from internal.chain_price.reader import ChainReader

    calls = []

    class _FinneyClient:
        timeout = 4.0
        retries = 1
        endpoint = "https://finney.example"

        def _call_typed(self, method, params):
            calls.append(("finney", method))
            if method == "chain_getFinalizedHead":
                return None
            return []

    class _BmClient:
        timeout = 4.0
        retries = 1
        endpoint = "https://bm.example"

        def _call_typed(self, method, params):
            calls.append(("blockmachine", method))
            if method == "chain_getFinalizedHead":
                return VALID_PINNED_HASH
            return []

    reader = ChainReader([("finney", _FinneyClient()), ("blockmachine", _BmClient())])
    block_hash, outcome = reader.pin_finalized_head()
    assert outcome == "ok"
    assert block_hash == VALID_PINNED_HASH
    assert reader.provider_served == "blockmachine"
    assert calls[0] == ("finney", "chain_getFinalizedHead")
    assert ("blockmachine", "chain_getFinalizedHead") in calls


@pytest.mark.parametrize(
    "bad_head",
    [None, "", "0x", "0x1234", "not-a-hash", 12345],
)
def test_invalid_finalized_head_shapes_fallback(bad_head):
    from internal.chain_price.reader import ChainReader

    calls = []

    class _FinneyClient:
        timeout = 4.0
        retries = 1
        endpoint = "https://finney.example"

        def _call_typed(self, method, params):
            calls.append(("finney", method))
            if method == "chain_getFinalizedHead":
                return bad_head
            return []

    class _BmClient:
        timeout = 4.0
        retries = 1
        endpoint = "https://bm.example"

        def _call_typed(self, method, params):
            calls.append(("blockmachine", method))
            if method == "chain_getFinalizedHead":
                return VALID_PINNED_HASH
            return []

    reader = ChainReader([("finney", _FinneyClient()), ("blockmachine", _BmClient())])
    block_hash, outcome = reader.pin_finalized_head()
    assert outcome == "ok"
    assert block_hash == VALID_PINNED_HASH
    assert reader.provider_served == "blockmachine"
    assert ("blockmachine", "chain_getFinalizedHead") in calls


def test_storage_after_pin_tries_pinned_provider_then_fallback():
    from internal.chain_price.reader import ChainReader

    storage_order = []

    class _FinneyClient:
        timeout = 4.0
        retries = 1
        endpoint = "https://finney.example"

        def _call_typed(self, method, params):
            if method == "chain_getFinalizedHead":
                return VALID_PINNED_HASH
            return []

        def query_storage_at(self, keys, at_hash):
            storage_order.append("finney")
            raise ChainRpcError("timeout", "read timed out")

    class _BmClient:
        timeout = 4.0
        retries = 1
        endpoint = "https://bm.example"

        def query_storage_at(self, keys, at_hash):
            storage_order.append("blockmachine")
            return [{"block": at_hash, "changes": []}]

    reader = ChainReader([("finney", _FinneyClient()), ("blockmachine", _BmClient())])
    assert reader.pin_finalized_head()[1] == "ok"
    _, outcome = reader.call("state_queryStorageAt", [[], VALID_PINNED_HASH])
    assert outcome == "ok"
    assert storage_order == ["finney", "blockmachine"]


def test_finney_connection_error_after_pin_storage_falls_back():
    from internal.chain_price.reader import ChainReader

    storage_order = []

    class _FinneyClient:
        timeout = 4.0
        retries = 1
        endpoint = "https://finney.example"

        def _call_typed(self, method, params):
            if method == "chain_getFinalizedHead":
                return VALID_PINNED_HASH
            return []

        def query_storage_at(self, keys, at_hash):
            storage_order.append("finney")
            raise ChainRpcError("connection", "connection refused")

    class _BmClient:
        timeout = 4.0
        retries = 1
        endpoint = "https://bm.example"

        def query_storage_at(self, keys, at_hash):
            storage_order.append("blockmachine")
            return [{"block": at_hash, "changes": []}]

    reader = ChainReader([("finney", _FinneyClient()), ("blockmachine", _BmClient())])
    assert reader.pin_finalized_head()[1] == "ok"
    _, outcome = reader.call("state_queryStorageAt", [[], VALID_PINNED_HASH])
    assert outcome == "ok"
    assert storage_order == ["finney", "blockmachine"]


def test_archive_miss_after_pin_falls_back_to_blockmachine():
    from internal.chain_price.reader import ChainReader

    storage_order = []

    class _FinneyClient:
        timeout = 4.0
        retries = 1
        endpoint = "https://finney.example"

        def _call_typed(self, method, params):
            if method == "chain_getFinalizedHead":
                return VALID_PINNED_HASH
            return []

        def query_storage_at(self, keys, at_hash):
            storage_order.append("finney")
            raise ChainRpcError("archive_miss", "State already discarded")

    class _BmClient:
        timeout = 4.0
        retries = 1
        endpoint = "https://bm.example"

        def query_storage_at(self, keys, at_hash):
            storage_order.append("blockmachine")
            return [{"block": at_hash, "changes": []}]

    reader = ChainReader([("finney", _FinneyClient()), ("blockmachine", _BmClient())])
    assert reader.pin_finalized_head()[1] == "ok"
    _, outcome = reader.call("state_queryStorageAt", [[], VALID_PINNED_HASH])
    assert outcome == "ok"
    assert storage_order == ["finney", "blockmachine"]


def test_backfill_reader_archive_miss_on_finney_falls_back():
    from internal.chain_price.reader import ChainReader

    class _FinneyClient:
        timeout = 4.0
        retries = 1
        endpoint = "https://finney.example"

        def _call_typed(self, method, params):
            if method == "chain_getHeader":
                raise ChainRpcError("archive_miss", "State already discarded")
            return VALID_PINNED_HASH

    class _BmClient:
        timeout = 4.0
        retries = 1
        endpoint = "https://bm.example"

        def _call_typed(self, method, params):
            if method == "chain_getHeader":
                return {"number": "0x1"}
            return []

    reader = ChainReader([("finney", _FinneyClient()), ("blockmachine", _BmClient())])
    reader.pin_finalized_head()
    header, outcome = reader.call("chain_getHeader", [VALID_PINNED_HASH])
    assert outcome == "ok"
    assert isinstance(header, dict)
    assert reader.provider_served == "blockmachine"


def test_reset_pin_clears_stick_so_next_head_tries_finney_first():
    from internal.chain_price.reader import ChainReader

    head_order = []
    storage_order = []
    finney_head_calls = [0]

    class _FinneyClient:
        timeout = 4.0
        retries = 1
        endpoint = "https://finney.example"

        def _call_typed(self, method, params):
            if method == "chain_getFinalizedHead":
                head_order.append("finney")
                finney_head_calls[0] += 1
                if finney_head_calls[0] == 1:
                    return None
                return VALID_PINNED_HASH
            return []

        def query_storage_at(self, keys, at_hash):
            storage_order.append("finney")
            return [{"block": at_hash, "changes": []}]

    class _BmClient:
        timeout = 4.0
        retries = 1
        endpoint = "https://bm.example"

        def _call_typed(self, method, params):
            if method == "chain_getFinalizedHead":
                head_order.append("blockmachine")
                return VALID_PINNED_HASH
            return []

        def query_storage_at(self, keys, at_hash):
            storage_order.append("blockmachine")
            return [{"block": at_hash, "changes": []}]

    reader = ChainReader([("finney", _FinneyClient()), ("blockmachine", _BmClient())])
    assert reader.pin_finalized_head()[1] == "ok"
    storage_order.clear()
    reader.call("state_queryStorageAt", [[], VALID_PINNED_HASH])
    assert storage_order == ["blockmachine"]

    reader.reset_pin()
    head_order.clear()
    storage_order.clear()
    assert reader.pin_finalized_head()[1] == "ok"
    reader.call("state_queryStorageAt", [[], VALID_PINNED_HASH])
    assert head_order[0] == "finney"
    assert storage_order == ["finney"]


def test_finney_read_timeout_falls_back_to_blockmachine(monkeypatch):
    from internal.chain_price.reader import ChainReader

    calls = []

    class _FinneyClient:
        timeout = 4.0
        retries = 1
        endpoint = "https://finney.example"

        def _call_typed(self, method, params):
            calls.append(("finney", method))
            raise ChainRpcError("timeout", "read timed out")

    class _BmClient:
        timeout = 4.0
        retries = 1
        endpoint = "https://bm.example"

        def _call_typed(self, method, params):
            calls.append(("blockmachine", method))
            if method == "chain_getFinalizedHead":
                return VALID_PINNED_HASH
            return []

    reader = ChainReader([("finney", _FinneyClient()), ("blockmachine", _BmClient())])
    block_hash, outcome = reader.pin_finalized_head()
    assert outcome == "ok"
    assert block_hash == VALID_PINNED_HASH
    assert reader.provider_served == "blockmachine"
    assert calls[0] == ("finney", "chain_getFinalizedHead")
    assert any(c[0] == "blockmachine" for c in calls)


def test_storage_short_changes_row_yields_parse_not_crash(monkeypatch):
    members = [1]

    def fake_pin(self):
        self.provider_served = "finney"
        return VALID_PINNED_HASH, "ok"

    def fake_call(self, method, params):
        if method == "state_queryStorageAt":
            tao_key = map_key_hex(b"SubnetTAO", 1)
            return [{"block": VALID_PINNED_HASH, "changes": [[tao_key]]}], "ok"
        if method == "chain_getFinalizedHead":
            return VALID_PINNED_HASH, "ok"
        return None, "rpc_error"

    member_fn = lambda _call, _at_hash: (members, "ok")
    monkeypatch.setattr("internal.chain_price.membership.get_member_netuids", member_fn)
    monkeypatch.setattr("internal.chain_price.live_subnet_snapshot.get_member_netuids", member_fn)
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.pin_finalized_head", fake_pin)
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.call", fake_call)
    batch = _fetch_snapshot_batch(monkeypatch, members)
    assert batch["netuid_outcomes"][1] == "parse"
    assert batch["rows"] == []


def test_storage_truncated_u64_rejected_not_padded(monkeypatch):
    members = [1]

    def fake_pin(self):
        self.provider_served = "finney"
        return VALID_PINNED_HASH, "ok"

    def fake_call(self, method, params):
        if method == "state_queryStorageAt":
            tao_key = map_key_hex(b"SubnetTAO", 1)
            alpha_key = map_key_hex(b"SubnetAlphaIn", 1)
            return [
                {
                    "block": VALID_PINNED_HASH,
                    "changes": [
                        [tao_key, "0x01"],
                        [alpha_key, _u64_storage_hex(1_000_000_000)],
                    ],
                }
            ], "ok"
        if method == "chain_getFinalizedHead":
            return VALID_PINNED_HASH, "ok"
        return None, "rpc_error"

    member_fn = lambda _call, _at_hash: (members, "ok")
    monkeypatch.setattr("internal.chain_price.membership.get_member_netuids", member_fn)
    monkeypatch.setattr("internal.chain_price.live_subnet_snapshot.get_member_netuids", member_fn)
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.pin_finalized_head", fake_pin)
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.call", fake_call)
    batch = _fetch_snapshot_batch(monkeypatch, members)
    assert batch["netuid_outcomes"][1] == "parse"
    assert batch["rows"] == []


def test_storage_unrequested_key_yields_invalid(monkeypatch):
    members = [1]

    def fake_pin(self):
        self.provider_served = "finney"
        return VALID_PINNED_HASH, "ok"

    def fake_call(self, method, params):
        if method == "state_queryStorageAt":
            extra = map_key_hex(b"SubnetTAO", 99)
            return [{"block": VALID_PINNED_HASH, "changes": [[extra, _u64_storage_hex(1)]]}], "ok"
        if method == "chain_getFinalizedHead":
            return VALID_PINNED_HASH, "ok"
        return None, "rpc_error"

    member_fn = lambda _call, _at_hash: (members, "ok")
    monkeypatch.setattr("internal.chain_price.membership.get_member_netuids", member_fn)
    monkeypatch.setattr("internal.chain_price.live_subnet_snapshot.get_member_netuids", member_fn)
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.pin_finalized_head", fake_pin)
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.call", fake_call)
    batch = _fetch_snapshot_batch(monkeypatch, members)
    assert batch["netuid_outcomes"][1] == "invalid"
    assert batch["rows"] == []


def test_storage_rpc_return_after_deadline_not_ok(monkeypatch):
    members = [1]
    deadline = time.monotonic() + 10.0
    clock = [time.monotonic()]

    def fake_pin(self):
        self.provider_served = "finney"
        return VALID_PINNED_HASH, "ok"

    def fake_storage(self, method, params):
        if method == "state_queryStorageAt":
            clock[0] = deadline + 1.0
            keys, _ = params
            changes = [
                [map_key_hex(b"SubnetTAO", 1), _u64_storage_hex(1_000_000_000)],
                [map_key_hex(b"SubnetAlphaIn", 1), _u64_storage_hex(1_000_000_000)],
            ]
            return [{"block": VALID_PINNED_HASH, "changes": changes}], "ok"
        if method == "chain_getFinalizedHead":
            return VALID_PINNED_HASH, "ok"
        return None, "rpc_error"

    member_fn = lambda _call, _at_hash: (members, "ok")
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr("internal.chain_price.membership.get_member_netuids", member_fn)
    monkeypatch.setattr("internal.chain_price.live_subnet_snapshot.get_member_netuids", member_fn)
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.pin_finalized_head", fake_pin)
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.call", fake_storage)
    batch = _fetch_snapshot_batch(monkeypatch, members, deadline=deadline)
    assert batch["netuid_outcomes"][1] == "batch_expired"
    assert batch["rows"] == []
    assert batch["batch_expired"] is True