import time
from unittest.mock import MagicMock, patch

import pytest

from internal.chain_rpc_errors import ChainRpcError
from internal.chain_price.storage_keys import map_key_hex


def _u64_storage_hex(value: int) -> str:
    return "0x" + int(value).to_bytes(8, "little").hex()


def _install_storage_batch_rpc_mock(monkeypatch, members, reserve_by_netuid, *, rpc_calls=None):
    """Patch ChainReader for batched snapshot tests (Finney-first path)."""
    if rpc_calls is None:
        rpc_calls = []

    def fake_pin(self):
        self.provider_served = "finney"
        return "0xblock", "ok"

    def fake_call(self, method, params):
        rpc_calls.append(method)
        if method == "chain_getFinalizedHead":
            return "0xblock", "ok"
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
            return [{"block": "0xblock", "changes": changes}], "ok"
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
        with pytest.raises(ChainRpcError) as exc2:
            second._call_typed("chain_getBlockHash", [])
        assert str(exc2.value) == "cooldown"
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
        with pytest.raises(ChainRpcError) as exc:
            client._call_typed("chain_getBlockHash", [])
        assert str(exc.value) == "cooldown"
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
    rows = client.get_subnet_price_rows([2, 1])
    assert [r["netuid"] for r in rows] == [1, 2]
    assert rows[0]["source"] == "finney"


def _deadline_after_first_storage_mock(monkeypatch, members, reserve_by_netuid, deadline: float):
    clock = [time.monotonic()]

    def fake_pin(self):
        self.provider_served = "finney"
        return "0xblock", "ok"

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
            return [{"block": "0xblock", "changes": changes}], "ok"
        if method == "chain_getFinalizedHead":
            return "0xblock", "ok"
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
    monkeypatch.setenv("LIVE_SUBNETS_STORAGE_CHUNK_NETUIDS", "1")
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_MONOTONIC", str(deadline))
    batch = client.get_subnet_price_rows_batch([2, 1])
    assert batch["batch_expired"] is True
    assert batch["netuid_outcomes"].get(2) == "batch_expired"


def test_storage_batch_128_netuids_constant_rpc_count(monkeypatch):
    from internal.chain_client import ChainClient

    client = ChainClient()
    members = list(range(1, 129))
    reserves = {n: (n * 1_000_000_000, 1_000_000_000) for n in members}
    rpc_calls = _install_storage_batch_rpc_mock(monkeypatch, members, reserves)
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_SECONDS", "85")

    batch_128 = client.get_subnet_price_rows_batch(members)
    count_128 = len(rpc_calls)
    assert len(batch_128["rows"]) == 128

    rpc_calls.clear()
    batch_hint = client.get_subnet_price_rows_batch(members[:10] + [200])
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
    batch = client.get_subnet_price_rows_batch([1, 2])
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
        return "0xblock", "ok"

    def fake_call(self, method, params):
        if method == "state_queryStorageAt":
            return None, "timeout"
        if method == "chain_getFinalizedHead":
            return "0xblock", "ok"
        return None, "rpc_error"

    member_fn = lambda _call, _at_hash: ([1, 2], "ok")
    monkeypatch.setattr("internal.chain_price.membership.get_member_netuids", member_fn)
    monkeypatch.setattr("internal.chain_price.live_subnet_snapshot.get_member_netuids", member_fn)
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.pin_finalized_head", fake_pin)
    monkeypatch.setattr("internal.chain_price.reader.ChainReader.call", fake_call)
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_SECONDS", "2")
    batch = client.get_subnet_price_rows_batch([1, 2])
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
    monkeypatch.setenv("LIVE_SUBNETS_STORAGE_CHUNK_NETUIDS", "1")
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_MONOTONIC", str(deadline))
    batch = client.get_subnet_price_rows_batch([2, 1])
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
    from internal.chain_client import ChainClient

    client = ChainClient()
    deadline = time.monotonic() + 0.1
    _deadline_after_first_storage_mock(
        monkeypatch,
        members=[1, 2, 3],
        reserve_by_netuid={
            1: (1_000_000_000, 1_000_000_000),
            2: (2_000_000_000, 1_000_000_000),
            3: (3_000_000_000, 1_000_000_000),
        },
        deadline=deadline,
    )
    monkeypatch.setenv("LIVE_SUBNETS_STORAGE_CHUNK_NETUIDS", "1")
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_MONOTONIC", str(deadline))
    batch = client.get_subnet_price_rows_batch([1, 2, 3])
    from internal.live_subnets_fetch_child import fetch_meta_from_batch

    meta = fetch_meta_from_batch(
        [1, 2, 3],
        batch["rows"],
        batch_expired=batch["batch_expired"],
        netuid_outcomes=batch["netuid_outcomes"],
    )
    assert meta["refresh_complete"] is False
    assert sorted(meta["missing_netuids"]) == sorted(
        [n for n in (1, 2, 3) if batch["netuid_outcomes"].get(n) != "ok"]
    )


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
    batch = client.get_subnet_price_rows_batch(universe)
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
                    return "0xblock", "ok"
                keys, _block_hash = params
                tao_key = map_key_hex(b"SubnetTAO", 1)
                if tao_key not in keys:
                    return [{"block": "0xblock", "changes": [[keys[0], "0x01"]]}], "ok"
                self.provider_served = "blockmachine"
                alpha_key = map_key_hex(b"SubnetAlphaIn", 1)
                changes = [
                    [tao_key, _u64_storage_hex(1_000_000_000)],
                    [alpha_key, _u64_storage_hex(1_000_000_000)],
                ]
                return [{"block": "0xblock", "changes": changes}], "ok"

            return _call

        def pin_finalized_head(self):
            self.provider_served = "finney"
            return "0xblock", "ok"

    monkeypatch.setattr("internal.chain_price.live_subnet_snapshot.ChainReader", _Reader)
    batch = client.get_subnet_price_rows_batch([1])
    assert batch["rows"][0]["source"] == "blockmachine"