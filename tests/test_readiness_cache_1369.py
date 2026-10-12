"""Issue #1369 — readiness cache staleness, request path, watchdog."""

from __future__ import annotations

import asyncio
import logging
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server import app


def _reset_cache():
    from internal.ops.readiness_cache import reset_readiness_cache

    reset_readiness_cache()


def test_stale_payload_marks_ready_false(monkeypatch):
    import internal.ops.readiness_cache as cache

    _reset_cache()
    monkeypatch.setattr(cache, "MAX_STALE_SECONDS", 60.0)
    stale = {"status": "ready", "ready": True, "issues": []}
    with cache._CACHE_LOCK:
        cache._CACHE["at"] = time.time() - 120.0
        cache._CACHE["payload"] = dict(stale)

    out = cache._envelope(dict(stale), cached=True, cache_age=120.0, serving_stale=True)
    assert out["ready"] is False
    assert out["status"] == "degraded"
    assert "readiness_stale" in out["issues"]


def test_get_path_does_not_invoke_build():
    _reset_cache()
    import internal.ops.readiness_cache as cache

    calls = {"n": 0}

    def _fake():
        calls["n"] += 1
        return {"status": "ready", "ready": True, "issues": []}

    with cache._CACHE_LOCK:
        cache._CACHE["at"] = time.time()
        cache._CACHE["payload"] = {"status": "ready", "ready": True, "issues": []}
    with patch("internal.ops.readiness.build_readiness_report", side_effect=_fake):
        with TestClient(app) as client:
            for _ in range(5):
                r = client.get("/api/ops/readiness")
                assert r.status_code == 200
    assert calls["n"] == 0


def test_section_timeout_recorded(monkeypatch):
    import internal.ops.readiness as readiness

    monkeypatch.setattr(readiness, "_SECTION_TIMEOUT", 0.01)

    def _slow():
        time.sleep(0.2)
        return {"graded": 1}

    with patch.object(readiness, "_learning_summary", _slow):
        report = readiness.build_readiness_report()
    assert any(i.startswith("readiness_section_timeout:") for i in report.get("issues", []))
    assert report.get("readiness_sections")


def test_background_failure_logs_warning(caplog):
    import internal.ops.readiness_cache as cache

    _reset_cache()
    caplog.set_level(logging.WARNING)

    def _boom():
        raise RuntimeError("boom")

    with patch("internal.ops.readiness_cache._build_blocking", side_effect=_boom):
        cache._kick_background_build()
        time.sleep(0.3)
    assert any("readiness background build failed" in r.message for r in caplog.records)


def test_watchdog_allows_next_build(monkeypatch):
    import internal.ops.readiness_cache as cache

    _reset_cache()
    monkeypatch.setattr(cache, "BUILD_WATCHDOG_SECONDS", 0.05)

    with cache._BUILD_SLOT_LOCK:
        cache._ACTIVE_BUILD_GENERATION = 1
        cache._BUILD_GENERATION = 1
        cache._BUILD_STARTED_AT = time.time() - 1.0

    gen = cache._try_begin_build()
    assert gen == 2
    cache._end_build(gen)


def test_section_timeout_returns_within_bound(monkeypatch):
    import internal.ops.readiness as readiness

    monkeypatch.setattr(readiness, "_SECTION_TIMEOUT", 0.05)

    def _slow():
        time.sleep(2.0)
        return {"graded": 1}

    started = time.perf_counter()
    with patch.object(readiness, "_learning_summary", _slow):
        readiness.build_readiness_report()
    assert time.perf_counter() - started < 0.5


def test_lifespan_refresher_warms_when_background_on_web_off(monkeypatch):
    import internal.ops.readiness_cache as cache

    _reset_cache()
    monkeypatch.setenv("BACKGROUND_ON_WEB", "off")
    monkeypatch.setattr(cache, "TTL", 0.05)

    def _fake_report():
        return {"status": "ready", "ready": True, "issues": ["warmed"]}

    with patch("internal.ops.readiness.build_readiness_report", side_effect=_fake_report):
        with TestClient(app) as client:
            client.get("/health")
            for _ in range(80):
                if cache._stale_copy():
                    break
                time.sleep(0.05)
    payload = cache._stale_copy()
    assert payload is not None
    assert "warmed" in (payload.get("issues") or [])


def _section_pool_thread_count() -> int:
    import threading

    return sum(1 for t in threading.enumerate() if t.name.startswith("readiness-section"))


def test_hung_section_bounded_threads_across_builds(monkeypatch):
    import internal.ops.readiness as readiness

    monkeypatch.setattr(readiness, "_SECTION_TIMEOUT", 0.05)
    hang = {"stop": False}

    def _block():
        while not hang["stop"]:
            time.sleep(0.02)
        return {"graded": 0}

    with patch.object(readiness, "_learning_summary", _block):
        readiness.build_readiness_report()
        baseline = _section_pool_thread_count()
        for _ in range(5):
            readiness.build_readiness_report()
        after_cycles = _section_pool_thread_count()
    hang["stop"] = True
    time.sleep(0.15)
    assert after_cycles - baseline <= 1


def test_abandoned_build_does_not_overwrite_cache():
    import internal.ops.readiness_cache as cache

    _reset_cache()
    with cache._CACHE_LOCK:
        cache._CACHE["payload"] = {"marker": "new", "ready": True, "issues": []}
        cache._CACHE["at"] = time.time()
    with cache._BUILD_SLOT_LOCK:
        cache._BUILD_GENERATION = 2
    out = cache._store_if_current({"marker": "old", "ready": False, "issues": []}, 1)
    assert out.get("marker") == "new"
    with cache._CACHE_LOCK:
        assert cache._CACHE["payload"]["marker"] == "new"


def _warm_thread_count() -> int:
    import threading

    return sum(1 for t in threading.enumerate() if t.name == "readiness-cache-warm")


def test_warm_reset_fences_old_worker(monkeypatch):
    """Blocked warm build → reset → re-kick must not leave two warm workers."""
    import threading

    import internal.ops.readiness_cache as cache

    _reset_cache()
    gate = threading.Event()
    calls = {"n": 0, "lock": threading.Lock()}

    def _blocking_build(*, force: bool = False):
        with calls["lock"]:
            calls["n"] += 1
        gate.wait(timeout=2.0)
        return {"status": "ready", "ready": True, "issues": []}

    with patch.object(cache, "_build_blocking", side_effect=_blocking_build):
        cache._kick_background_build()
        for _ in range(40):
            if calls["n"] >= 1:
                break
            time.sleep(0.02)
        assert calls["n"] >= 1
        assert _warm_thread_count() == 1
        cache.reset_readiness_cache()
        gate.set()
        for _ in range(40):
            if _warm_thread_count() == 0:
                break
            time.sleep(0.02)
        gate.clear()
        with calls["lock"]:
            calls["n"] = 0
        cache._kick_background_build()
        for _ in range(40):
            if calls["n"] >= 1:
                break
            time.sleep(0.02)
        assert _warm_thread_count() == 1
        cache._kick_background_build()
        assert _warm_thread_count() == 1
        gate.set()
        for _ in range(40):
            if _warm_thread_count() == 0:
                break
            time.sleep(0.02)
        cache.reset_readiness_cache()
    assert calls["n"] == 1


def test_refresher_reset_fences_old_loop(monkeypatch):
    """Blocked build → reset → restart must not double refresher cadence."""
    import threading

    import internal.ops.readiness_cache as cache

    _reset_cache()
    monkeypatch.setattr(cache, "TTL", 0.12)
    gate = threading.Event()
    calls = {"n": 0, "lock": threading.Lock()}

    def _blocking_build(*, force: bool = False):
        with calls["lock"]:
            calls["n"] += 1
        gate.wait(timeout=2.0)
        return {"status": "ready", "ready": True, "issues": []}

    with patch.object(cache, "_build_blocking", side_effect=_blocking_build):
        cache.start_readiness_refresher()
        for _ in range(40):
            if calls["n"] >= 1:
                break
            time.sleep(0.02)
        assert calls["n"] >= 1
        cache.reset_readiness_cache()
        gate.set()
        with calls["lock"]:
            calls["n"] = 0
        cache.start_readiness_refresher()
        time.sleep(0.17)
        cache.stop_readiness_refresher()
        cache.reset_readiness_cache()
    assert calls["n"] == 1


def test_build_failure_increments_metric():
    from prometheus_client import REGISTRY

    import internal.ops.readiness_cache as cache

    _reset_cache()
    before = REGISTRY.get_sample_value(
        "readiness_build_failures_total", {"reason": "RuntimeError"}
    )
    cache._record_build_failure("RuntimeError")
    after = REGISTRY.get_sample_value(
        "readiness_build_failures_total", {"reason": "RuntimeError"}
    )
    assert (after or 0) > (before or 0)
