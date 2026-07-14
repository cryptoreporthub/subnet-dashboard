"""Lazy OHLCV fill for cold price_cache (audit #16 continuation)."""

from internal.council.state_vector import _get_price_history, _history_from_candles


def _sample_candles(n: int = 32):
    return [
        {
            "timestamp": f"2026-01-{i:02d}T00:00:00Z",
            "open": 1.0 + i * 0.01,
            "high": 1.05 + i * 0.01,
            "low": 0.95 + i * 0.01,
            "close": 1.0 + i * 0.01,
            "volume": 100.0,
        }
        for i in range(1, n + 1)
    ]


def test_history_from_candles_honest_empty_under_30():
    hist = _history_from_candles(_sample_candles(10), "taomarketcap")
    assert hist["source"] == "unavailable"
    assert hist["closes"] == []


def test_lazy_fill_populates_cold_cache(monkeypatch):
    monkeypatch.setattr("internal.council.state_vector._load_price_cache", lambda: {})

    def _fake_fetch(netuid, use_cache=True, **kwargs):
        assert netuid == "7"
        assert kwargs.get("allow_synthetic") is False
        return _sample_candles(32)

    monkeypatch.setattr(
        "internal.indicators.price_fetcher.fetch_ohlcv",
        _fake_fetch,
    )

    hist = _get_price_history(7, {"netuid": 7})
    assert len(hist["closes"]) == 32
    assert hist["source"] in ("taomarketcap", "lazy_fill", "cached")


def test_lazy_fill_skipped_for_synthetic_cache(monkeypatch):
    monkeypatch.setattr(
        "internal.council.state_vector._load_price_cache",
        lambda: {"7": {"source": "synthetic", "candles": _sample_candles(40)}},
    )
    called = {"n": 0}

    def _should_not_fetch(*_a, **_k):
        called["n"] += 1
        return []

    monkeypatch.setattr(
        "internal.indicators.price_fetcher.fetch_ohlcv",
        _should_not_fetch,
    )

    hist = _get_price_history(7, {"netuid": 7})
    assert hist["closes"] == []
    assert called["n"] == 0


def test_price_history_unavailable_when_lazy_fill_empty(monkeypatch):
    monkeypatch.setattr("internal.council.state_vector._load_price_cache", lambda: {})
    monkeypatch.setattr(
        "internal.council.state_vector._lazy_fill_price_candles",
        lambda _nid: [],
    )
    hist = _get_price_history(1, {"netuid": 1, "price": 1.0})
    assert hist["source"] == "unavailable"
    assert hist["closes"] == []
