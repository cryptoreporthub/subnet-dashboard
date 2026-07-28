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


def test_webhook_subscribe_rejects_private_ip():
    from internal.webhook_url import validate_webhook_url

    with pytest.raises(ValueError, match="not allowed"):
        validate_webhook_url("https://127.0.0.1/hook")
    with pytest.raises(ValueError, match="https"):
        validate_webhook_url("http://example.com/hook")
    assert validate_webhook_url("https://hooks.example.com/alerts") == "https://hooks.example.com/alerts"
