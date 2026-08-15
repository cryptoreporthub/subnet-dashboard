"""Critical resolver and daily scoring paths stay local-cache only."""

from __future__ import annotations

from internal.council.daily_pick import select_daily_pick
from internal.council.state_vector import score_subnet_for_day
import internal.council.resolver_scheduler as resolver_scheduler


def _scoring_rows(count: int = 24) -> list[dict]:
    return [
        {
            "netuid": netuid,
            "name": f"SN{netuid}",
            "price": 1.0,
            "volume": 10_000.0,
            "market_cap": 1_000_000.0,
            "emission": 1.0,
            "apy": 20.0,
            "price_change_24h": 1.0,
            "price_change_7d": 2.0,
            "price_change_30d": 3.0,
            "status": "active",
        }
        for netuid in range(1, count + 1)
    ]


def test_resolver_provider_uses_worker_cache_without_network(monkeypatch):
    cached = [{"netuid": 7, "price": 1.25, "volume": 10.0}]

    monkeypatch.setattr(
        "internal.live_subnets.get_live_subnets",
        lambda: cached,
    )
    monkeypatch.setattr(
        "fetchers.taomarketcap.get_all_subnets",
        lambda: (_ for _ in ()).throw(AssertionError("TaoMarketCap must not run")),
    )

    assert resolver_scheduler._default_subnets() == cached


def test_daily_scoring_does_not_hydrate_cold_price_cache(monkeypatch):
    monkeypatch.setattr(
        "internal.council.state_vector._load_price_cache",
        lambda: {},
    )
    calls: list[str] = []

    def _unexpected_fetch(netuid, **_kwargs):
        calls.append(str(netuid))
        raise AssertionError("daily scoring must not hydrate OHLCV")

    monkeypatch.setattr(
        "internal.indicators.price_fetcher.fetch_ohlcv",
        _unexpected_fetch,
    )

    rows = _scoring_rows()
    for row in rows:
        result = score_subnet_for_day(row, {"skip_pump_overlay": True})
        assert result["horizon_type"] == "day"

    pick = select_daily_pick(rows, {"skip_pump_overlay": True})

    assert pick["subnet"]["netuid"] in range(1, 25)
    assert calls == []
