"""Tests for the technical indicator layer."""

import json

import pytest

from internal.indicators.price_fetcher import (
    _fetch_geckoterminal_ohlcv,
    _fetch_tmc_subnet_candles,
    _price_sources_for_subnet,
    _synthetic_candles,
    fetch_ohlcv,
)

def test_price_sources_default_to_taomarketcap():
    pairs = {"5": {"symbol": "KAON"}}
    sources = _price_sources_for_subnet("5", pairs)
    assert sources[0]["source"] == "taomarketcap"
    assert sources[0]["netuid"] == "5"

def test_price_sources_include_geckoterminal_fallback():
    pairs = {
        "5": {
            "symbol": "KAON",
            "geckoterminal": {
                "network": "bittensor",
                "pool": "0-5",
                "base_is_alpha": True,
            },
        }
    }
    sources = _price_sources_for_subnet("5", pairs)
    assert sources[0]["source"] == "geckoterminal"
    assert sources[0]["network"] == "bittensor"
    assert sources[1]["source"] == "taomarketcap"
    assert sources[-1]["source"] == "blockmachine"
    assert not any(s["source"] == "synthetic" for s in sources)


def test_gecko_orientation_audit_artifact_covers_all_mappings():
    """Committed audit must match every geckoterminal block in price_pairs.json."""
    from pathlib import Path

    pairs = json.load(open("config/price_pairs.json"))
    audit = json.load(open("docs/gecko-pool-orientation-audit.json"))
    gecko_netuids = sorted(
        k
        for k, v in pairs.items()
        if isinstance(v, dict) and isinstance(v.get("geckoterminal"), dict)
    )
    rows = audit.get("rows") or []
    assert audit.get("gecko_mapping_count") == len(gecko_netuids) == 100
    assert len(rows) == 100
    assert audit.get("unknown_or_error_count") == 0
    by_netuid = {str(r["netuid"]): r for r in rows}
    assert set(by_netuid) == set(gecko_netuids)
    for uid in gecko_netuids:
        assert by_netuid[uid]["orientation"] == "alpha_base_tao_quote"
        assert pairs[uid]["geckoterminal"].get("base_is_alpha") is True


def test_unaudited_gecko_mapping_skips_gecko_tier():
    """Pools without explicit audited orientation must not use the gecko tier."""
    pairs = {
        "5": {
            "symbol": "KAON",
            "geckoterminal": {"network": "bittensor", "pool": "0-5"},
        }
    }
    sources = _price_sources_for_subnet("5", pairs)
    assert not any(s["source"] == "geckoterminal" for s in sources)


def test_price_sources_skip_gecko_without_explicit_orientation():
    pairs = {
        "5": {
            "symbol": "KAON",
            "geckoterminal": {"network": "bittensor", "pool": "0-5"},
        }
    }
    sources = _price_sources_for_subnet("5", pairs)
    assert not any(s["source"] == "geckoterminal" for s in sources)
    assert sources[0]["source"] == "taomarketcap"


def test_synthetic_candles_are_deterministic():
    a = _synthetic_candles("subnet-7", days=2)
    b = _synthetic_candles("subnet-7", days=2)
    assert len(a) == len(b) == 48
    assert a[0] == b[0]
    assert a[-1] == b[-1]

def test_fetch_tmc_subnet_candles_scales_by_alpha_price(monkeypatch):
    def fake_subnets():
        return {"5": {"latest_snapshot": {"price": 0.5}}}

    def fake_candles(days=1):
        return [
            {
                "timestamp": "2024-01-01T00:00:00+00:00",
                "open": 100,
                "high": 110,
                "low": 90,
                "close": 105,
                "volume": 1000,
            },
            {
                "timestamp": "2024-01-01T01:00:00+00:00",
                "open": 105,
                "high": 115,
                "low": 95,
                "close": 110,
                "volume": 2000,
            },
        ]

    monkeypatch.setattr(
        "internal.indicators.price_fetcher._fetch_tmc_subnets", fake_subnets
    )
    monkeypatch.setattr(
        "internal.indicators.price_fetcher._fetch_tmc_candles", fake_candles
    )

    candles = _fetch_tmc_subnet_candles("5", days=1)
    assert len(candles) == 2
    assert candles[0]["close"] == 52.5
    assert candles[0]["volume"] == 1000

def test_fetch_geckoterminal_ohlcv_parses_response(monkeypatch):
    import requests

    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": {
                    "attributes": {
                        "ohlcv_list": [
                            [1704067200, 1.0, 2.0, 0.5, 1.5, 100.0],
                            [1704070800, 1.5, 2.5, 1.0, 2.0, 200.0],
                        ]
                    }
                }
            }

    def fake_get(url, params=None, **kwargs):
        captured["params"] = params
        return FakeResp()

    monkeypatch.setattr(requests, "get", fake_get)
    candles = _fetch_geckoterminal_ohlcv("bittensor", "0-5", days=1)
    assert len(candles) == 2
    assert candles[0]["open"] == 1.0
    assert candles[0]["close"] == 1.5
    assert captured["params"] == {"limit": 24, "currency": "token"}


def test_fetch_geckoterminal_ohlcv_requests_token_not_usd_default(monkeypatch):
    """#1397: default Gecko OHLCV is USD; subnet grading expects TAO (token)."""
    import requests

    usd_close = 18.99
    tao_close = 0.0682

    def fake_get(url, params=None, **kwargs):
        currency = (params or {}).get("currency")
        close = tao_close if currency == "token" else usd_close

        class Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "data": {
                        "attributes": {
                            "ohlcv_list": [
                                [1704067200, close, close, close, close, 1.0],
                                [1704070800, close, close, close, close, 1.0],
                            ]
                        }
                    }
                }

        return Resp()

    monkeypatch.setattr(requests, "get", fake_get)
    candles = _fetch_geckoterminal_ohlcv("bittensor", "0-64", days=1)
    assert candles[-1]["close"] == tao_close
    assert candles[-1]["close"] != usd_close

def test_fetch_ohlcv_uses_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("internal.indicators.price_fetcher.USE_LIVE_PRICES", False)
    cache_path = tmp_path / "price_cache.json"
    pairs_path = tmp_path / "price_pairs.json"
    json.dump({"1": {"symbol": "SN1"}}, open(pairs_path, "w"))

    candles = fetch_ohlcv(
        "1",
        days=2,
        use_cache=True,
        cache_path=str(cache_path),
        pairs_path=str(pairs_path),
        allow_synthetic=True,
    )
    assert len(candles) == 48
    assert cache_path.exists()

    cached = fetch_ohlcv(
        "1",
        days=2,
        use_cache=True,
        cache_path=str(cache_path),
        pairs_path=str(pairs_path),
        allow_synthetic=True,
    )
    assert cached == candles

def test_fetch_ohlcv_tiered_fallback_to_geckoterminal(monkeypatch, tmp_path):
    import requests

    cache_path = tmp_path / "price_cache.json"
    pairs_path = tmp_path / "price_pairs.json"
    json.dump(
        {
            "1": {
                "symbol": "SN1",
                "geckoterminal": {
                    "network": "bittensor",
                    "pool": "0-1",
                    "base_is_alpha": True,
                },
            }
        },
        open(pairs_path, "w"),
    )

    def fake_get(url, **kwargs):
        if "taomarketcap" in url:

            class Bad:
                def raise_for_status(self):
                    raise RuntimeError("TMC down")

                def json(self):
                    return {}

            return Bad()

        class Good:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "data": {
                        "attributes": {
                            "ohlcv_list": [
                            [1704067200, 1.0, 2.0, 0.5, 1.5, 100.0],
                            [1704070800, 1.5, 2.5, 1.0, 2.0, 200.0],
                        ]
                        }
                    }
                }

        return Good()

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr("internal.indicators.price_fetcher.USE_LIVE_PRICES", True)

    candles = fetch_ohlcv(
        "1", days=1, use_cache=True, cache_path=str(cache_path), pairs_path=str(pairs_path)
    )
    assert len(candles) == 2
    cache = json.load(open(cache_path))
    assert cache["1"]["source"] == "geckoterminal"
    assert cache["1"]["unit"] == "tao"
def test_price_sources_include_blockmachine_fallback():
    pairs = {"5": {"symbol": "KAON"}}
    sources = _price_sources_for_subnet("5", pairs)
    assert sources[0]["source"] == "taomarketcap"
    assert any(s["source"] == "blockmachine" for s in sources)
    assert not any(s["source"] == "synthetic" for s in sources)


def test_fetch_ohlcv_empty_without_synthetic(tmp_path, monkeypatch):
    monkeypatch.setattr("internal.indicators.price_fetcher.USE_LIVE_PRICES", False)
    cache_path = tmp_path / "price_cache.json"
    pairs_path = tmp_path / "price_pairs.json"
    json.dump({"1": {"symbol": "SN1"}}, open(pairs_path, "w"))

    candles = fetch_ohlcv(
        "1", days=2, use_cache=True, cache_path=str(cache_path), pairs_path=str(pairs_path)
    )
    assert candles == []
    cache = json.load(open(cache_path))
    assert cache["1"]["source"] == "unavailable"


def test_gecko_ohlcv_guarantees_alpha_in_tao_orientations():
    from internal.indicators.price_fetcher import gecko_ohlcv_guarantees_alpha_in_tao

    alpha_base = {"network": "bittensor", "pool": "0-1", "base_is_alpha": True}
    assert gecko_ohlcv_guarantees_alpha_in_tao(alpha_base)
    assert gecko_ohlcv_guarantees_alpha_in_tao({**alpha_base, "price_token": "base"})

    tao_base = {"network": "bittensor", "pool": "x", "base_is_alpha": False}
    assert not gecko_ohlcv_guarantees_alpha_in_tao({**tao_base, "price_token": "base"})
    assert gecko_ohlcv_guarantees_alpha_in_tao({**tao_base, "price_token": "quote"})

    unknown = {"network": "bittensor", "pool": "0-99"}
    assert not gecko_ohlcv_guarantees_alpha_in_tao(unknown)


def test_fetch_geckoterminal_ohlcv_price_token_param(monkeypatch):
    import requests

    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "data": {
                    "attributes": {
                        "ohlcv_list": [
                            [1704067200, 1.0, 1.0, 1.0, 1.0, 1.0],
                            [1704070800, 1.0, 1.0, 1.0, 1.0, 1.0],
                        ]
                    }
                }
            }

    def fake_get(url, params=None, **kwargs):
        captured["params"] = params
        return FakeResp()

    monkeypatch.setattr(requests, "get", fake_get)
    _fetch_geckoterminal_ohlcv(
        "bittensor",
        "0-1",
        days=1,
        gecko_cfg={"price_token": "quote", "base_is_alpha": False},
    )
    assert captured["params"] == {"limit": 24, "currency": "token", "token": "quote"}


def test_fetch_ohlcv_legacy_gecko_refetch_failure_is_unavailable(monkeypatch, tmp_path):
    import time

    monkeypatch.setattr("internal.indicators.price_fetcher.USE_LIVE_PRICES", True)
    monkeypatch.setattr(
        "internal.indicators.price_fetcher._fetch_geckoterminal_ohlcv",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("gecko down")),
    )
    monkeypatch.setattr(
        "internal.indicators.price_fetcher._price_sources_for_subnet",
        lambda *a, **k: [{"source": "geckoterminal", "network": "bittensor", "pool": "0-1", "gecko_cfg": {}}],
    )
    cache_path = tmp_path / "price_cache.json"
    pairs_path = tmp_path / "price_pairs.json"
    json.dump({"1": {"symbol": "SN1"}}, open(pairs_path, "w"))
    json.dump(
        {
            "1": {
                "source": "geckoterminal",
                "cached_at": time.time(),
                "candles": [
                    {
                        "timestamp": "2026-10-14T00:00:00+00:00",
                        "open": 80.0,
                        "high": 80.0,
                        "low": 80.0,
                        "close": 80.0,
                        "volume": 1.0,
                    }
                ],
            }
        },
        open(cache_path, "w"),
    )
    candles = fetch_ohlcv(
        "1",
        days=2,
        use_cache=True,
        cache_path=str(cache_path),
        pairs_path=str(pairs_path),
    )
    assert candles == []
    assert json.load(open(cache_path))["1"]["source"] == "unavailable"


def test_fetch_ohlcv_refetches_untagged_geckoterminal_cache(monkeypatch, tmp_path):
    """Legacy untagged GeckoTerminal entries are USD closes: refetch, don't serve."""
    import time

    monkeypatch.setattr("internal.indicators.price_fetcher.USE_LIVE_PRICES", True)
    monkeypatch.setattr(
        "internal.indicators.price_fetcher._price_sources_for_subnet",
        lambda *a, **k: [
            {
                "source": "geckoterminal",
                "network": "bittensor",
                "pool": "0-1",
                "gecko_cfg": {
                    "network": "bittensor",
                    "pool": "0-1",
                    "base_is_alpha": True,
                },
            }
        ],
    )
    calls = []
    fresh = [
        {"timestamp": "2026-10-15T00:00:00+00:00", "open": 0.27, "high": 0.27, "low": 0.27, "close": 0.27, "volume": 1.0}
    ]

    def fake_gecko(network, pool, days=2, **kwargs):
        calls.append(pool)
        return fresh

    monkeypatch.setattr("internal.indicators.price_fetcher._fetch_geckoterminal_ohlcv", fake_gecko)
    cache_path = tmp_path / "price_cache.json"
    pairs_path = tmp_path / "price_pairs.json"
    json.dump({"1": {"symbol": "SN1"}}, open(pairs_path, "w"))
    usd_candle = {"timestamp": "2026-10-14T00:00:00+00:00", "open": 80.0, "high": 80.0, "low": 80.0, "close": 80.0, "volume": 1.0}
    json.dump(
        {"1": {"source": "geckoterminal", "cached_at": time.time(), "candles": [usd_candle]}},
        open(cache_path, "w"),
    )
    kwargs = dict(days=2, use_cache=True, cache_path=str(cache_path), pairs_path=str(pairs_path))

    assert fetch_ohlcv("1", **kwargs) == fresh
    assert calls == ["0-1"]
    assert json.load(open(cache_path))["1"]["unit"] == "tao"

    # A TAO-tagged entry within TTL is served from cache without refetching.
    assert fetch_ohlcv("1", **kwargs) == fresh
    assert calls == ["0-1"]


def test_fetch_ohlcv_tiered_fallback_to_blockmachine(monkeypatch, tmp_path):
    class FakeClient:
        degraded = False

        def is_healthy(self):
            return True

        def get_alpha_price(self, netuid):
            return 0.5

    monkeypatch.setattr(
        "internal.indicators.price_fetcher._get_chain_client", lambda: FakeClient()
    )
    monkeypatch.setattr(
        "internal.indicators.price_fetcher._fetch_tmc_candles",
        lambda: [
            {
                "timestamp": "2024-01-01T00:00:00+00:00",
                "open": 100,
                "high": 110,
                "low": 90,
                "close": 105,
                "volume": 1000,
            },
            {
                "timestamp": "2024-01-01T01:00:00+00:00",
                "open": 105,
                "high": 115,
                "low": 95,
                "close": 110,
                "volume": 2000,
            },
        ],
    )

    import requests

    def fake_get(url, **kwargs):
        class Bad:
            def raise_for_status(self):
                raise RuntimeError("source down")

            def json(self):
                return {}

        return Bad()

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr("internal.indicators.price_fetcher.USE_LIVE_PRICES", True)

    cache_path = tmp_path / "price_cache.json"
    pairs_path = tmp_path / "price_pairs.json"
    json.dump({"501": {"symbol": "SN501"}}, open(pairs_path, "w"))

    candles = fetch_ohlcv(
        "501", days=1, use_cache=True, cache_path=str(cache_path), pairs_path=str(pairs_path)
    )
    assert len(candles) == 2
    assert candles[0]["close"] == 52.5
    cache = json.load(open(cache_path))
    assert cache["501"]["source"] == "blockmachine_derived"
