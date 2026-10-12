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
    import internal.ops.readiness_cache as cache

    with cache._CACHE_LOCK:
        cache._CACHE["at"] = 0.0
        cache._CACHE["payload"] = None
    with cache._BUILD_SLOT_LOCK:
        cache._BUILD_IN_FLIGHT = 0
        cache._BUILD_STARTED_AT = 0.0
    cache._BUILD_INVOCATIONS = 0


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
        cache._BUILD_IN_FLIGHT = 1
        cache._BUILD_STARTED_AT = time.time() - 1.0

    assert cache._try_begin_build() is True
    cache._end_build()


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
