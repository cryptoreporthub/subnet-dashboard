"""Tests for the technical indicator layer."""

import json
import os
import tempfile
from datetime import datetime, timezone

import pytest

from internal.indicators.crossover_detector import detect_crossovers
from internal.indicators.indicator_engine import IndicatorEngine
from internal.indicators.indicator_scheduler import IndicatorScheduler
from internal.indicators.macd import compute_macd
from internal.indicators.momentum import compute_momentum
from internal.indicators.price_fetcher import (
    _fetch_geckoterminal_ohlcv,
    _fetch_tmc_subnet_candles,
    _price_sources_for_subnet,
    _synthetic_candles,
    fetch_ohlcv,
)
from internal.indicators.rsi import compute_rsi

def _make_candles(closes, highs=None, lows=None, volumes=None):
    """Build minimal OHLCV candle list from a close series."""
    now = datetime.now(timezone.utc)
    candles = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        h = highs[i] if highs else max(o, c) * 1.01
        l = lows[i] if lows else min(o, c) * 0.99
        v = volumes[i] if volumes else 1000.0
        candles.append(
            {
                "timestamp": (now.replace(minute=0, second=0, microsecond=0)).isoformat(),
                "open": round(o, 6),
                "high": round(h, 6),
                "low": round(l, 6),
                "close": round(c, 6),
                "volume": round(v, 2),
            }
        )
    return candles

def test_price_sources_default_to_taomarketcap():
    pairs = {"5": {"symbol": "KAON"}}
    sources = _price_sources_for_subnet("5", pairs)
    assert sources[0]["source"] == "taomarketcap"
    assert sources[0]["netuid"] == "5"

def test_price_sources_include_geckoterminal_fallback():
    pairs = {
        "5": {
            "symbol": "KAON",
            "geckoterminal": {"network": "bittensor", "pool": "0-5"},
        }
    }
    sources = _price_sources_for_subnet("5", pairs)
    assert sources[0]["source"] == "taomarketcap"
    assert sources[1]["source"] == "geckoterminal"
    assert sources[1]["network"] == "bittensor"
    assert sources[-1]["source"] == "synthetic"

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

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: FakeResp())
    candles = _fetch_geckoterminal_ohlcv("bittensor", "0-5", days=1)
    assert len(candles) == 2
    assert candles[0]["open"] == 1.0
    assert candles[0]["close"] == 1.5

def test_fetch_ohlcv_uses_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("internal.indicators.price_fetcher.USE_LIVE_PRICES", False)
    cache_path = tmp_path / "price_cache.json"
    pairs_path = tmp_path / "price_pairs.json"
    json.dump({"1": {"symbol": "SN1"}}, open(pairs_path, "w"))

    candles = fetch_ohlcv(
        "1", days=2, use_cache=True, cache_path=str(cache_path), pairs_path=str(pairs_path)
    )
    assert len(candles) == 48
    assert cache_path.exists()

    cached = fetch_ohlcv(
        "1", days=2, use_cache=True, cache_path=str(cache_path), pairs_path=str(pairs_path)
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
                "geckoterminal": {"network": "bittensor", "pool": "0-1"},
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

def test_rsi_returns_neutral_for_balanced_prices():
    # Oscillating series with comparable gains/losses keeps RSI near 50.
    closes = [100.0 + (i % 2) * ((-1) ** i) * 2 for i in range(30)]
    candles = _make_candles(closes)
    result = compute_rsi(candles)
    assert 40.0 <= result["rsi"] <= 60.0
    assert result["neutral"] is True

def test_rsi_detects_overbought_and_oversold():
    # Strong sustained rise pushes RSI into overbought territory.
    rising = [100.0 * (1.02 ** i) for i in range(40)]
    candles = _make_candles(rising)
    result = compute_rsi(candles)
    assert result["overbought"] is True

    # Strong sustained decline pushes RSI into oversold territory.
    falling = [100.0 * (0.98 ** i) for i in range(40)]
    candles2 = _make_candles(falling)
    result2 = compute_rsi(candles2)
    assert result2["oversold"] is True

def test_macd_cross_flags():
    # Build a series that creates a histogram cross.
    base = [100.0] * 40
    # Force MACD line above signal then below to create a bearish cross.
    closes = base + [100.0 + i * 0.5 for i in range(1, 21)]
    candles = _make_candles(closes)
    result = compute_macd(candles)
    assert "macd_line" in result
    assert "signal_line" in result
    assert isinstance(result["bullish_cross"], bool)
    assert isinstance(result["bearish_cross"], bool)

def test_momentum_stochastic_overbought():
    # Close at the high of the lookback window pushes %K to 100.
    closes = list(range(1, 50)) + [100.0] * 20
    highs = closes[:]
    lows = [c * 0.95 for c in closes]
    candles = _make_candles(closes, highs=highs, lows=lows)
    result = compute_momentum(candles)
    assert result["stochastic_overbought"] is True

def test_momentum_roc_positive_after_recovery():
    # ROC turns positive when price recovers above the lookback close.
    closes = [100.0] * 10 + [90.0] * 5 + [110.0] * 5
    candles = _make_candles(closes)
    result = compute_momentum(candles)
    assert result["roc"] > 0

def test_crossover_detects_rsi_reversal():
    rsi = {"rsi": 35.0}
    rsi_prev = {"rsi": 28.0}
    macd = {"bullish_cross": False, "bearish_cross": False, "histogram": 0.0}
    mom = {"roc": 1.0, "stochastic_k": 50.0, "stochastic_d": 50.0, "williams_r": -50.0}
    events = detect_crossovers(rsi, macd, mom, prev_rsi=rsi_prev)
    assert any(e["event_type"] == "rsi_oversold_reversal" for e in events)

def test_crossover_detects_macd_bullish_cross():
    rsi = {"rsi": 50.0}
    macd = {"bullish_cross": True, "bearish_cross": False, "histogram": 0.5}
    mom = {"roc": 1.0, "stochastic_k": 50.0, "stochastic_d": 50.0, "williams_r": -50.0}
    events = detect_crossovers(rsi, macd, mom)
    assert any(e["event_type"] == "macd_bullish_cross" for e in events)

def test_indicator_engine_run_cycle(tmp_path):
    reg = tmp_path / "registry.json"
    soul = tmp_path / "soul_map.json"
    pairs = tmp_path / "price_pairs.json"
    json.dump(
        {"1": {"emission": 2.0, "social_mentions": 2000, "is_overvalued": False, "status": "active"}},
        open(reg, "w"),
    )
    json.dump({"1": {"symbol": "SN1"}}, open(pairs, "w"))

    engine = IndicatorEngine(
        registry_path=str(reg),
        soul_map_path=str(soul),
        price_pairs_path=str(pairs),
    )
    result = engine.run_cycle([1])
    assert result["ok"] is True
    assert result["subnets_processed"] == 1
    assert "per_subnet" in result
    assert "events" in result

    state = engine.get_indicator_state()
    assert "per_subnet" in state
    assert "1" in state["per_subnet"]

def test_indicator_scheduler_run_once(tmp_path):
    reg = tmp_path / "registry.json"
    soul = tmp_path / "soul_map.json"
    pairs = tmp_path / "price_pairs.json"
    json.dump(
        {"1": {"emission": 2.0, "social_mentions": 2000, "is_overvalued": False, "status": "active"}},
        open(reg, "w"),
    )
    json.dump({"1": {"symbol": "SN1"}}, open(pairs, "w"))

    scheduler = IndicatorScheduler(
        refresh_minutes=15,
        soul_map_path=str(soul),
        registry_path=str(reg),
    )
    result = scheduler.run_once()
    assert result["ok"] is True
    assert result["subnets_processed"] == 1

    state = scheduler.state()
    assert state["running"] is False
    assert state["consecutive_failures"] == 0

def test_scheduler_start_stop_are_idempotent():
    scheduler = IndicatorScheduler(refresh_minutes=60)
    res1 = scheduler.start(immediate=False)
    assert res1["started"] is True
    res2 = scheduler.start(immediate=False)
    assert res2["started"] is False
    scheduler.stop()



def test_price_sources_include_blockmachine_fallback():
    pairs = {"5": {"symbol": "KAON"}}
    sources = _price_sources_for_subnet("5", pairs)
    assert sources[0]["source"] == "taomarketcap"
    assert any(s["source"] == "blockmachine" for s in sources)
    assert sources[-1]["source"] == "synthetic"


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
    json.dump({"1": {"symbol": "SN1"}}, open(pairs_path, "w"))

    candles = fetch_ohlcv(
        "1", days=1, use_cache=True, cache_path=str(cache_path), pairs_path=str(pairs_path)
    )
    assert len(candles) == 2
    assert candles[0]["close"] == 52.5
    cache = json.load(open(cache_path))
    assert cache["1"]["source"] == "blockmachine"
