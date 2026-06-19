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
    _coingecko_id_for_subnet,
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


def test_coingecko_id_lookup_uses_mapping():
    pairs = {"1": {"coingecko_id": "bittensor", "symbol": "TAO"}}
    assert _coingecko_id_for_subnet("1", pairs) == "bittensor"


def test_coingecko_id_unknown_falls_back():
    pairs = {"1": {"coingecko_id": "unknown", "symbol": "SN99"}}
    assert _coingecko_id_for_subnet("99", pairs) == "subnet-99"


def test_synthetic_candles_are_deterministic():
    a = _synthetic_candles("subnet-7", days=2)
    b = _synthetic_candles("subnet-7", days=2)
    assert len(a) == len(b) == 48
    assert a[0] == b[0]
    assert a[-1] == b[-1]


def test_fetch_ohlcv_uses_cache(tmp_path):
    cache_path = tmp_path / "price_cache.json"
    pairs_path = tmp_path / "price_pairs.json"
    json.dump({"1": {"coingecko_id": "unknown", "symbol": "SN1"}}, open(pairs_path, "w"))

    candles = fetch_ohlcv("1", days=2, use_cache=True, cache_path=str(cache_path))
    assert len(candles) == 48
    assert cache_path.exists()

    cached = fetch_ohlcv("1", days=2, use_cache=True, cache_path=str(cache_path))
    assert cached == candles


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
    json.dump({"1": {"coingecko_id": "unknown", "symbol": "SN1"}}, open(pairs, "w"))

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
    json.dump({"1": {"coingecko_id": "unknown", "symbol": "SN1"}}, open(pairs, "w"))

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
