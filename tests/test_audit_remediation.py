"""Audit remediation P0/P1 — readiness cache, write auth, webhook SSRF guard."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from server import app


def test_ops_live_is_fast_and_minimal():
    with TestClient(app) as client:
        t0 = time.monotonic()
        r = client.get("/api/ops/live")
        elapsed = time.monotonic() - t0
    assert r.status_code == 200
    assert elapsed < 1.0
    body = r.json()
    assert body.get("status") in ("ok", "degraded")
    assert "volume" in body
    assert "worker_peer" in body


def _reset_readiness_cache():
    import internal.ops.readiness_cache as cache

    with cache._CACHE_LOCK:
        cache._CACHE["at"] = 0.0
        cache._CACHE["payload"] = None


def test_readiness_uses_cache(monkeypatch):
    _reset_readiness_cache()
    import internal.ops.readiness_cache as cache

    calls = {"n": 0}

    def _fake_build():
        calls["n"] += 1
        return {"status": "ready", "ready": True, "issues": []}

    monkeypatch.setattr(cache, "TTL", 60.0)
    monkeypatch.setattr(cache, "BUILD_TIMEOUT", 2.0)
    with patch("internal.ops.readiness.build_readiness_report", side_effect=_fake_build):
        with TestClient(app) as client:
            r1 = client.get("/api/ops/readiness")
            r2 = client.get("/api/ops/readiness")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.json().get("cached") is True
    assert calls["n"] == 1


def test_readiness_refresh_bypasses_cache(monkeypatch):
    _reset_readiness_cache()
    import internal.ops.readiness_cache as cache

    calls = {"n": 0}

    def _fake_build():
        calls["n"] += 1
        return {"status": "ready", "ready": True, "issues": []}

    monkeypatch.setattr(cache, "TTL", 60.0)
    with patch("internal.ops.readiness.build_readiness_report", side_effect=_fake_build):
        with TestClient(app) as client:
            client.get("/api/ops/readiness")
            client.get("/api/ops/readiness?refresh=true")
    assert calls["n"] == 2


def test_readiness_timeout_serves_stale_primary(monkeypatch):
    """Under build timeout, return last good report — not a naked busy shell."""
    _reset_readiness_cache()
    import asyncio
    import internal.ops.readiness_cache as cache

    stale = {
        "status": "ready",
        "ready": True,
        "issues": [],
        "learning": {"graded": 1, "pending": 0},
    }
    with cache._CACHE_LOCK:
        cache._CACHE["at"] = time.time() - 120.0
        cache._CACHE["payload"] = dict(stale)

    monkeypatch.setattr(cache, "TTL", 30.0)
    monkeypatch.setattr(cache, "BUILD_TIMEOUT", 0.05)

    def _slow_build(*, force: bool = False):
        time.sleep(1.0)
        return {"status": "ready", "ready": True, "issues": []}

    monkeypatch.setattr(cache, "_build_blocking", _slow_build)

    async def _run():
        return await cache.get_readiness_report(force=True)

    out = asyncio.run(_run())
    assert out.get("ready") is True
    assert out.get("serving_stale") is True
    assert out.get("cached") is True
    assert "readiness_build_slow" in (out.get("issues") or [])
    assert "readiness_build_slow" in (out.get("advisories") or [])
    assert out.get("blocking_issues") == []
    assert out.get("status") == "ready"


def test_readiness_busy_lock_does_not_block(monkeypatch):
    _reset_readiness_cache()
    import internal.ops.readiness_cache as cache

    held = cache._BUILD_LOCK.acquire(blocking=False)
    assert held
    try:
        with cache._CACHE_LOCK:
            cache._CACHE["at"] = time.time() - 120.0
            cache._CACHE["payload"] = {"status": "ready", "ready": True, "issues": []}
        out = cache._build_blocking(force=False)
        assert out.get("ready") is True
    finally:
        cache._BUILD_LOCK.release()


def test_write_auth_blocks_ingest_when_token_set(monkeypatch):
    monkeypatch.setenv("WRITE_API_TOKEN", "secret-test-token")
    with TestClient(app) as client:
        denied = client.post("/api/message-intel/ingest", json={"content": "hi"})
        assert denied.status_code == 401
        ok = client.post(
            "/api/message-intel/ingest",
            json={"content": "hi"},
            headers={"Authorization": "Bearer secret-test-token"},
        )
    assert ok.status_code == 200


def test_write_auth_open_when_token_unset(monkeypatch):
    monkeypatch.delenv("WRITE_API_TOKEN", raising=False)
    with TestClient(app) as client:
        r = client.post("/api/message-intel/ingest", json={"content": "audit-open"})
    assert r.status_code == 200


def test_resolve_true_requires_token_when_enabled(monkeypatch):
    monkeypatch.setenv("WRITE_API_TOKEN", "resolve-token")
    with TestClient(app) as client:
        denied = client.get("/api/predictions/resolved?resolve=true")
        assert denied.status_code == 401
        ok = client.get(
            "/api/predictions/resolved?resolve=true",
            headers={"Authorization": "Bearer resolve-token"},
        )
    assert ok.status_code == 200


def test_write_auth_default_deny_admin_posts(monkeypatch):
    """Admin/state mutations require bearer when token is set."""
    monkeypatch.setenv("WRITE_API_TOKEN", "admin-token")
    headers = {"Authorization": "Bearer admin-token"}
    with TestClient(app) as client:
        for path, body in (
            ("/api/learning/trigger", {}),
            ("/api/predictions/resolver/run", {}),
            ("/api/alerts", {"alert_type": "manual", "message": "t", "severity": "info"}),
        ):
            denied = client.post(path, json=body)
            assert denied.status_code == 401, path
            ok = client.post(path, json=body, headers=headers)
            assert ok.status_code != 401, path


def test_write_auth_public_writes_open_with_token_set(monkeypatch):
    """Browser UX POSTs stay open without bearer when token is set."""
    monkeypatch.setenv("WRITE_API_TOKEN", "admin-token")
    with TestClient(app) as client:
        for path, body in (
            ("/api/mindmap/feedback", {"note": "public-ux"}),
            ("/api/feedback", {"feedback": "public-ux"}),
        ):
            r = client.post(path, json=body)
            assert r.status_code != 401, path


def test_write_auth_wrong_token_rejected(monkeypatch):
    monkeypatch.setenv("WRITE_API_TOKEN", "correct-token")
    with TestClient(app) as client:
        r = client.post(
            "/api/message-intel/ingest",
            json={"content": "hi"},
            headers={"Authorization": "Bearer wrong-token"},
        )
    assert r.status_code == 401


def test_webhook_subscribe_rejects_private_ip():
    from internal.webhook_url import validate_webhook_url

    with pytest.raises(ValueError, match="not allowed"):
        validate_webhook_url("https://127.0.0.1/hook")
    with pytest.raises(ValueError, match="https"):
        validate_webhook_url("http://example.com/hook")
    assert validate_webhook_url("https://hooks.example.com/alerts") == "https://hooks.example.com/alerts"
