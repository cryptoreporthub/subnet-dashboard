import time


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

    client.get_alpha_price = price
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

    client.get_alpha_price = price
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

    client.get_alpha_price = price
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

    client.get_alpha_price = price
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


def test_price_batch_rpc_error_is_fetch_errors_not_batch_deadline(monkeypatch):
    from internal.chain_client import ChainClient

    client = ChainClient.__new__(ChainClient)
    monkeypatch.setenv("LIVE_SUBNETS_LITE_WORKERS", "2")
    monkeypatch.setenv("LIVE_SUBNETS_BATCH_DEADLINE_SECONDS", "2")
    client.is_healthy = lambda: True

    def price(netuid):
        if netuid == 2:
            raise RuntimeError("rpc down")
        return float(netuid)

    client.get_alpha_price = price
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

    client.get_alpha_price = price
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
    client.get_alpha_price = lambda netuid: 1.0

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
    client.get_alpha_price = slow_price
    batch = client.get_subnet_price_rows_batch([1])
    outcomes = dict(batch["netuid_outcomes"])
    time.sleep(0.25)
    assert batch["netuid_outcomes"] == outcomes
    assert outcomes.get(1) == "batch_expired"