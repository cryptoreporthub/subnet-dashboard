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


def test_normalize_waits_for_price_cache_lock(tmp_path):
    """A startup rename must not replace a file a sibling writer is updating."""
    cache_path = tmp_path / "price_cache.json"
    cache_path.write_text(json.dumps({"01": {"candles": [1]}}))
    started = threading.Event()
    release = threading.Event()

    def hold():
        with pf._locked_price_cache(str(cache_path)):
            started.set()
            assert release.wait(timeout=5)
            latest = pf._load_json(str(cache_path))
            latest["2"] = {"candles": [2]}
            pf._save_json(str(cache_path), latest)

    holder = threading.Thread(target=hold)
    holder.start()
    assert started.wait(timeout=5)

    from internal.council.price_reference import normalize_price_cache_keys

    outcome = {}

    def rename():
        outcome["renamed"] = normalize_price_cache_keys(str(cache_path))

    renamer = threading.Thread(target=rename)
    renamer.start()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and not renamer.is_alive() and "renamed" not in outcome:
        time.sleep(0.01)
    assert "renamed" not in outcome
    assert renamer.is_alive()
    release.set()
    renamer.join(timeout=5)
    holder.join(timeout=5)

    assert outcome["renamed"] == 1
    saved = json.loads(cache_path.read_text())
    assert "1" in saved
    assert "2" in saved
    assert "01" not in saved
