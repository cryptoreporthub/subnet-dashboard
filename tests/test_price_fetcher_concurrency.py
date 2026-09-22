"""Price-cache lost-update and negative-cache TTL."""

import json
import threading
import time

import internal.indicators.price_fetcher as pf


def test_concurrent_fetches_keep_both_subnet_keys(tmp_path, monkeypatch):
    cache_path = tmp_path / "price_cache.json"
    monkeypatch.setattr(pf, "USE_LIVE_PRICES", True)
    started = threading.Barrier(2)

    def fake_candles(netuid, days=7):
        started.wait(timeout=5)
        return [{"close": float(netuid), "source_netuid": str(netuid)}]

    monkeypatch.setattr(pf, "_fetch_tmc_subnet_candles", fake_candles)

    errors = []

    def run(netuid):
        try:
            pf.fetch_ohlcv(netuid, cache_path=str(cache_path), use_cache=True)
        except Exception as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(netuid,)) for netuid in ("1", "2")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    saved = json.loads(cache_path.read_text())
    assert set(saved) >= {"1", "2"}
    assert saved["1"]["candles"][0]["close"] == 1.0
    assert saved["2"]["candles"][0]["close"] == 2.0


def test_unavailable_cache_expires_after_30_seconds(tmp_path, monkeypatch):
    cache_path = tmp_path / "price_cache.json"
    now = time.time()
    cache_path.write_text(
        json.dumps(
            {
                "1": {
                    "source": "unavailable",
                    "cached_at": now - 31,
                    "candles": [],
                }
            }
        )
    )
    monkeypatch.setattr(pf, "USE_LIVE_PRICES", True)
    calls = {"n": 0}

    def fake_candles(netuid, days=7):
        calls["n"] += 1
        return [{"close": 9.0}]

    monkeypatch.setattr(pf, "_fetch_tmc_subnet_candles", fake_candles)
    candles = pf.fetch_ohlcv("1", cache_path=str(cache_path), use_cache=True)
    assert calls["n"] == 1
    assert candles[0]["close"] == 9.0


def test_unavailable_cache_hits_inside_30_seconds(tmp_path, monkeypatch):
    cache_path = tmp_path / "price_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "1": {
                    "source": "unavailable",
                    "cached_at": time.time() - 10,
                    "candles": [],
                }
            }
        )
    )
    monkeypatch.setattr(pf, "USE_LIVE_PRICES", True)
    calls = {"n": 0}

    def fake_candles(netuid, days=7):
        calls["n"] += 1
        return [{"close": 9.0}]

    monkeypatch.setattr(pf, "_fetch_tmc_subnet_candles", fake_candles)
    candles = pf.fetch_ohlcv("1", cache_path=str(cache_path), use_cache=True)
    assert calls["n"] == 0
    assert candles == []


def test_bust_and_fetch_keep_both_keys(tmp_path, monkeypatch):
    cache_path = tmp_path / "price_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "1": {"source": "taomarketcap", "cached_at": time.time(), "candles": [{"close": 1.0}]},
                "9": {"source": "taomarketcap", "cached_at": time.time(), "candles": [{"close": 9.0}]},
            }
        )
    )
    monkeypatch.setattr(pf, "USE_LIVE_PRICES", True)
    started = threading.Barrier(2)

    def fake_candles(netuid, days=7):
        started.wait(timeout=5)
        return [{"close": 2.0}]

    monkeypatch.setattr(pf, "_fetch_tmc_subnet_candles", fake_candles)

    from internal.council.price_reference import _bust_cache_ttl

    errors = []

    def bust():
        try:
            started.wait(timeout=5)
            _bust_cache_ttl(1, str(cache_path))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    def fetch():
        try:
            pf.fetch_ohlcv("2", cache_path=str(cache_path), use_cache=True)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=bust), threading.Thread(target=fetch)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert errors == []
    saved = json.loads(cache_path.read_text())
    assert "2" in saved and "9" in saved
    assert saved["1"]["cached_at"] == 0.0


def test_lock_timeout_returns_fetched_candles(tmp_path, monkeypatch):
    cache_path = tmp_path / "price_cache.json"
    monkeypatch.setattr(pf, "USE_LIVE_PRICES", True)
    monkeypatch.setattr(pf, "_fetch_tmc_subnet_candles", lambda netuid, days=7: [{"close": 4.0}])

    from contextlib import contextmanager

    @contextmanager
    def boom(path, timeout_seconds=5.0):
        raise TimeoutError("locked")
        yield  # pragma: no cover

    monkeypatch.setattr(pf, "_locked_price_cache", boom)
    candles = pf.fetch_ohlcv("3", cache_path=str(cache_path), use_cache=True)
    assert candles[0]["close"] == 4.0
    assert not cache_path.exists()
