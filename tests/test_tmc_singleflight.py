"""Tests for tmc_singleflight: one HTTP refetch per expiry under concurrency."""

import threading
import time

import internal.indicators.price_fetcher as pf
from internal.indicators import tmc_singleflight as tsf


def _reset(monkeypatch):
    tsf.uninstall_for_tests()
    monkeypatch.setattr(pf, "_tmc_subnets_cache", {"data": None, "cached_at": 0.0})
    monkeypatch.setattr(pf, "_tmc_candles_cache", {"data": None, "cached_at": 0.0})


def _fake_response(payload):
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    return R()


def test_single_flight_one_refetch_under_concurrency(monkeypatch):
    _reset(monkeypatch)
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _fake_response({"results": [{"netuid": i} for i in range(3)]})

    monkeypatch.setattr(pf.requests, "get", fake_get)
    tsf.install_once()

    results = [None] * 8

    def worker(i):
        results[i] = pf._fetch_tmc_subnets()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(calls) == 1
    assert results[0] is not None
    assert all(r == results[0] for r in results)


def test_expired_ttl_refetches_exactly_once_again(monkeypatch):
    _reset(monkeypatch)
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if "candle-data" in url:
            return _fake_response([])
        return _fake_response({"results": []})

    monkeypatch.setattr(pf.requests, "get", fake_get)
    monkeypatch.setattr(pf, "TMC_CACHE_TTL_SECONDS", 60)
    tsf.install_once()

    first = pf._fetch_tmc_candles()
    assert len(calls) == 1

    # Simulate expiry without changing wall clock much: rewind cached_at.
    pf._tmc_candles_cache["cached_at"] = time.time() - 10_000
    second = pf._fetch_tmc_candles()
    assert second == first
    assert len(calls) == 2  # one refresh per expiry, not N


def test_exception_propagates_and_lock_released(monkeypatch):
    _reset(monkeypatch)

    def boom(url, **kwargs):
        raise RuntimeError("tmc down")

    monkeypatch.setattr(pf.requests, "get", boom)
    tsf.install_once()

    try:
        pf._fetch_tmc_subnets()
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError to propagate")

    # Lock must be free afterwards: a later success path works.
    monkeypatch.setattr(pf.requests, "get", lambda url, **kw: _fake_response({"results": []}))
    pf._tmc_subnets_cache["cached_at"] = 0.0
    assert pf._fetch_tmc_subnets() == {}


def test_prewarm_returns_false_without_raising(monkeypatch):
    _reset(monkeypatch)

    def boom(url, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(pf.requests, "get", boom)
    tsf.install_once()
    assert tsf.prewarm() is False
