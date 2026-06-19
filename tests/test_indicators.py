"""Tests for the technical indicator layer."""

import os
import tempfile

import pytest

from indicators.crossover_detector import detect_sma_cross, detect_macd_cross, detect_all_crossovers
from indicators.indicator_engine import (
    IndicatorEngine,
    _classify_signal,
    _compute_conviction,
)
from indicators.learning import load_thresholds, tune_thresholds_from_verdicts
from indicators.macd import compute_macd
from indicators.momentum import compute_momentum
from indicators.rsi import compute_rsi


def test_rsi_overbought():
    prices = [1.0] * 14 + [2.0] * 5
    rsi = compute_rsi(prices, period=14)
    assert rsi is not None
    assert rsi > 70


def test_rsi_oversold():
    prices = [2.0] * 14 + [1.0] * 5
    rsi = compute_rsi(prices, period=14)
    assert rsi is not None
    assert rsi < 30


def test_macd_bullish_trend():
    prices = list(range(1, 50))
    macd = compute_macd(prices)
    assert macd is not None
    assert macd["trend"] == "bullish"


def test_macd_bearish_trend():
    prices = list(range(50, 1, -1))
    macd = compute_macd(prices)
    assert macd is not None
    assert macd["trend"] == "bearish"


def test_momentum_positive():
    prices = list(range(1, 20))
    momentum = compute_momentum(prices, period=10)
    assert momentum is not None
    assert momentum > 0


def test_momentum_negative():
    prices = list(range(20, 1, -1))
    momentum = compute_momentum(prices, period=10)
    assert momentum is not None
    assert momentum < 0


def test_golden_cross_detected():
    # Low prices then sustained rise crossing the SMA50.
    base = [100.0] * 55
    for i in range(-20, 0):
        base[i] = 100.0 + (20 + i) * 2
    cross = detect_sma_cross(base, fast_span=20, slow_span=50)
    assert cross is not None
    assert cross["type"] == "golden_cross"


def test_macd_cross_detection():
    macd = [-1.0, -0.5, 0.1, 1.0]
    signal = [0.0, -0.1, 0.05, 0.2]
    cross = detect_macd_cross(macd, signal)
    assert cross is not None
    assert cross["type"] == "macd_bullish_cross"


def test_classify_breakout():
    rsi = 55.0
    macd = {"trend": "bullish", "histogram": 0.5}
    momentum = 1.0
    thresholds = {"rsi_oversold": 30, "rsi_overbought": 70, "momentum_threshold": 3}
    crosses = [{"type": "golden_cross", "signal_type": "breakout"}]
    result = _classify_signal(rsi, macd, momentum, thresholds, crosses)
    assert result["signal_type"] == "breakout"
    assert result["action"] == "accumulate"


def test_classify_mean_reversion():
    rsi = 20.0
    macd = {"trend": "bullish", "histogram": 0.3}
    momentum = -1.0
    thresholds = {"rsi_oversold": 30, "rsi_overbought": 70, "momentum_threshold": 3}
    result = _classify_signal(rsi, macd, momentum, thresholds, [])
    assert result["signal_type"] == "mean_reversion"


def test_conviction_capped():
    classification = {"priority": 95}
    rsi = 80.0
    macd = {"histogram": 5.0}
    momentum = 20.0
    thresholds = {"conviction_floor": 30}
    conviction = _compute_conviction(classification, rsi, macd, momentum, thresholds)
    assert 0 <= conviction <= 100
    assert conviction >= 95


def test_engine_backtest_returns_data():
    engine = IndicatorEngine()
    # Without calling run(), pair not configured should return an error payload.
    result = engine.backtest_data("FAKE-PAIR")
    assert "error" in result


def test_load_thresholds_defaults():
    thresholds = load_thresholds()
    assert "rsi_oversold" in thresholds
    assert "rsi_overbought" in thresholds


def test_tune_thresholds_with_empty_verdicts():
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["SOUL_MAP_PATH"] = os.path.join(tmpdir, "soul_map.json")
        os.environ["INDICATOR_STATE_PATH"] = os.path.join(tmpdir, "indicator_state.json")
        thresholds = tune_thresholds_from_verdicts()
        assert thresholds["rsi_oversold"] == 30.0


def test_all_crossovers_empty():
    prices = [100.0] * 10
    crosses = detect_all_crossovers(prices)
    assert crosses == []
