import time
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import MagicMock, patch

import pytest

from internal.chain_rpc_errors import ChainRpcError


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


def test_parse_retry_after_header_delay_seconds_and_junk(clear_endpoint_rate_limits):
    from internal.chain_client import _parse_retry_after_header

    resp = MagicMock()
    resp.headers = {"Retry-After": "120"}
    assert _parse_retry_after_header(resp) == 120.0
    resp.headers = {"Retry-After": "not-a-date"}
    assert _parse_retry_after_header(resp) is None
    resp.headers = {"Retry-After": "-5"}
    assert _parse_retry_after_header(resp) is None


def test_parse_retry_after_header_http_date_naive_future(clear_endpoint_rate_limits):
    from internal.chain_client import _parse_retry_after_header

    wall = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)
    future = wall + timedelta(seconds=600)
    naive = future.strftime("%a, %d %b %Y %H:%M:%S")
    resp = MagicMock()
    resp.headers = {"Retry-After": naive}
    with patch("internal.chain_client.time.time", return_value=wall.timestamp()):
        assert _parse_retry_after_header(resp) == 600.0


def test_parse_retry_after_header_http_date_past_is_zero(clear_endpoint_rate_limits):
    from internal.chain_client import _parse_retry_after_header

    wall = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)
    past = wall - timedelta(minutes=10)
    resp = MagicMock()
    resp.headers = {"Retry-After": format_datetime(past, usegmt=True)}
    with patch("internal.chain_client.time.time", return_value=wall.timestamp()):
        assert _parse_retry_after_header(resp) == 0.0


def test_reader_retry_after_http_date_future(clear_endpoint_rate_limits):
    from internal.chain_client import ChainClient, rate_limited_until
    from internal.chain_price.reader import ChainReader

    client = ChainClient("https://finney.example", init_volume_db=False, retries=0)
    reader = ChainReader([("finney", client)])
    wall_ts = 1_700_000_000.0
    wall = datetime.fromtimestamp(wall_ts, tz=timezone.utc)
    future = wall + timedelta(seconds=600)
    header = format_datetime(future, usegmt=True)
    mono = [5000.0]
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {"Retry-After": header}
    with patch("internal.chain_client.time.time", return_value=wall_ts), patch(
        "internal.chain_client.time.monotonic", side_effect=lambda: mono[0]
    ), patch("internal.chain_price.reader.time.monotonic", side_effect=lambda: mono[0]):
        with patch("internal.chain_client.requests.post", return_value=resp):
            _, outcome = reader.call("chain_getFinalizedHead", [])
        assert outcome == "rate_limited"
        assert rate_limited_until(client.endpoint) - mono[0] >= 599.0


def test_reader_retry_after_http_date_past_no_negative_cooldown(clear_endpoint_rate_limits):
    from internal.chain_client import ChainClient, rate_limited_until
    from internal.chain_price.reader import ChainReader

    client = ChainClient("https://finney.example", init_volume_db=False, retries=0)
    reader = ChainReader([("finney", client)])
    wall_ts = 1_700_000_000.0
    wall = datetime.fromtimestamp(wall_ts, tz=timezone.utc)
    past = wall - timedelta(minutes=10)
    mono = [8000.0]
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {"Retry-After": format_datetime(past, usegmt=True)}
    with patch("internal.chain_client.time.time", return_value=wall_ts), patch(
        "internal.chain_client.time.monotonic", side_effect=lambda: mono[0]
    ), patch("internal.chain_price.reader.time.monotonic", side_effect=lambda: mono[0]):
        with patch("internal.chain_client.requests.post", return_value=resp):
            _, outcome = reader.call("chain_getFinalizedHead", [])
        assert outcome == "rate_limited"
        remaining = rate_limited_until(client.endpoint) - mono[0]
        assert remaining >= 0.0
        assert remaining == 60.0


def test_reader_retry_after_zero_explicit_contract(clear_endpoint_rate_limits):
    from internal.chain_client import ChainClient, rate_limited_until
    from internal.chain_price.reader import ChainReader

    client = ChainClient("https://finney.example", init_volume_db=False, retries=0)
    reader = ChainReader([("finney", client)])
    mono = [100.0]
    resp = MagicMock()
    resp.status_code = 429
    resp.headers = {"Retry-After": "0"}
    with patch("internal.chain_client.time.monotonic", side_effect=lambda: mono[0]), patch(
        "internal.chain_price.reader.time.monotonic", side_effect=lambda: mono[0]
    ):
        with patch("internal.chain_client.requests.post", return_value=resp):
            _, outcome = reader.call("chain_getFinalizedHead", [])
        assert outcome == "rate_limited"
        # Explicit zero: no extended deadline; reader re-note may apply default ladder.
        assert rate_limited_until(client.endpoint) <= mono[0] + 60.0


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


def test_price_batch_deadline_returns_completed_rows(monkeypatch):
    from internal.chain_client import ChainClient

    client = ChainClient.__new__(ChainClient)
    monkeypatch.setenv("LIVE_SUBNETS_LITE_WORKERS", "2")
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_SECONDS", "0.05")
    client.is_healthy = lambda: True

    def price(netuid):
        if netuid == 2:
            time.sleep(0.2)
        return float(netuid)

    client.get_alpha_price_probed = lambda n: (price(n), "ok")
    client.get_pool_state = lambda _n: None
    rows = client.get_subnet_price_rows([2, 1])

    assert rows == [{
        "netuid": 1,
        "name": "SN1",
        "price": 1.0,
        "source": "blockmachine",
    }]


def test_batch_deadline_honors_parent_monotonic_deadline(monkeypatch):
    from internal.chain_client import ChainClient

    client = ChainClient.__new__(ChainClient)
    monkeypatch.setenv("LIVE_SUBNETS_LITE_WORKERS", "2")
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_SECONDS", "85")
    monkeypatch.setenv(
        "LIVE_SUBNETS_BATCH_DEADLINE_MONOTONIC",
        str(time.monotonic() + 0.08),
    )
    client.is_healthy = lambda: True

    def price(netuid):
        if netuid == 2:
            time.sleep(0.25)
        return float(netuid)

    client.get_alpha_price_probed = lambda n: (price(n), "ok")
    client.get_pool_state = lambda _n: None
    rows = client.get_subnet_price_rows([2, 1])
    assert [r["netuid"] for r in rows] == [1]


def test_price_batch_deadline_includes_executor_shutdown(monkeypatch):
    from internal.chain_client import ChainClient

    client = ChainClient.__new__(ChainClient)
    monkeypatch.setenv("LIVE_SUBNETS_LITE_WORKERS", "4")
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_SECONDS", "0.12")
    client.is_healthy = lambda: True

    def price(netuid):
        if netuid >= 3:
            time.sleep(0.35)
        return float(netuid)

    client.get_alpha_price_probed = lambda n: (price(n), "ok")
    client.get_pool_state = lambda _n: None
    started = time.monotonic()
    rows = client.get_subnet_price_rows([1, 2, 3, 4, 5])
    elapsed = time.monotonic() - started
    assert {r["netuid"] for r in rows} == {1, 2}
    assert elapsed < 0.35


def test_price_batch_no_price_is_fetch_errors_not_batch_deadline(monkeypatch):
    from internal.chain_client import ChainClient

    client = ChainClient.__new__(ChainClient)
    monkeypatch.setenv("LIVE_SUBNETS_LITE_WORKERS", "2")
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_SECONDS", "2")
    client.is_healthy = lambda: True

    def price(netuid):
        if netuid == 2:
            return None
        return float(netuid)

    def probed(netuid):
        if netuid == 2:
            return None, "no_price"
        return float(netuid), "ok"

    client.get_alpha_price_probed = probed
    client.get_pool_state = lambda _n: None
    batch = client.get_subnet_price_rows_batch([1, 2])
    assert batch["batch_expired"] is False
    assert batch["netuid_outcomes"][2] == "no_price"
    from internal.live_subnets_fetch_child import fetch_meta_from_batch

    meta = fetch_meta_from_batch(
        [1, 2],
        batch["rows"],
        batch_expired=batch["batch_expired"],
        netuid_outcomes=batch["netuid_outcomes"],
    )
    assert meta["degraded_reason"] == "fetch_errors"


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
    assert outcome_err == "rpc_error"
    assert price_err is None
    price_none, outcome_none = client.get_alpha_price_probed(3)
    assert outcome_none == "no_price"
    assert price_none is None
    assert client.get_alpha_price(2) is None
    assert client.get_alpha_price(3) is None


def test_price_batch_rpc_error_is_fetch_errors_not_batch_deadline(monkeypatch):
    from internal.chain_client import ChainClient

    client = ChainClient.__new__(ChainClient)
    monkeypatch.setenv("LIVE_SUBNETS_LITE_WORKERS", "2")
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_SECONDS", "2")
    client.is_healthy = lambda: True

    def call(method, params):
        netuid = params[0]
        if netuid == 2:
            raise RuntimeError("rpc down")
        return int(netuid) * 1_000_000_000

    client._call = call
    client.get_pool_state = lambda _n: None
    batch = client.get_subnet_price_rows_batch([1, 2])
    assert batch["batch_expired"] is False
    assert batch["netuid_outcomes"][2] == "rpc_error"
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

    client = ChainClient.__new__(ChainClient)
    monkeypatch.setenv("LIVE_SUBNETS_LITE_WORKERS", "2")
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_SECONDS", "0.08")
    client.is_healthy = lambda: True

    def price(netuid):
        if netuid == 2:
            import time

            time.sleep(0.25)
        return float(netuid)

    client.get_alpha_price_probed = lambda n: (price(n), "ok")
    client.get_pool_state = lambda _n: None
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


def test_slow_pool_after_price_does_not_claim_ok_before_deadline(monkeypatch):
    from internal.chain_client import ChainClient

    client = ChainClient.__new__(ChainClient)
    monkeypatch.setenv("LIVE_SUBNETS_LITE_WORKERS", "1")
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_SECONDS", "0.05")
    client.is_healthy = lambda: True
    client.get_alpha_price_probed = lambda netuid: (1.0, "ok")

    def slow_pool(_netuid):
        time.sleep(0.15)
        return {"liquidity": 1.0}

    client.get_pool_state = slow_pool
    batch = client.get_subnet_price_rows_batch([1])
    assert batch["rows"] == []
    assert batch["batch_expired"] is True
    assert batch["netuid_outcomes"][1] == "batch_expired"


def test_outcomes_immutable_after_batch_return(monkeypatch):
    from internal.chain_client import ChainClient

    client = ChainClient.__new__(ChainClient)
    monkeypatch.setenv("LIVE_SUBNETS_LITE_WORKERS", "1")
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_SECONDS", "0.08")
    client.is_healthy = lambda: True

    def slow_price(netuid):
        time.sleep(0.2)
        return float(netuid)

    client.get_pool_state = lambda _n: None
    client.get_alpha_price_probed = lambda n: (slow_price(n), "ok")
    batch = client.get_subnet_price_rows_batch([1])
    outcomes = dict(batch["netuid_outcomes"])
    time.sleep(0.25)
    assert batch["netuid_outcomes"] == outcomes
    assert outcomes.get(1) == "batch_expired"