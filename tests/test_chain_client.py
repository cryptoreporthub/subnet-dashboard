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