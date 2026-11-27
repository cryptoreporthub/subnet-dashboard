"""Audit remediation P0/P1 — readiness cache, write auth, webhook SSRF guard."""

from __future__ import annotations

import functools
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import internal.council.mindmap_bridge as mindmap_bridge
import internal.council.resolver as resolver
import internal.council.weights as weights
import internal.investigation.routes as investigation_routes
import internal.simivision.chat_service as chat_service
from datastore import learning_engine
from internal.council.weights import load_weights
from internal.learning import predictions_store
from server import app


def _isolate_learning_writes(tmp_path, monkeypatch):
    """Keep resolver/feedback tests off repo ``data/soul_map.json`` and predictions."""
    soul_path = str(tmp_path / "soul_map.json")
    pred_path = str(tmp_path / "predictions.json")
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", soul_path)
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", pred_path)
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", pred_path)

    Path(soul_path).write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "council_weights": {
                        "quant": 1.0,
                        "hype": 1.0,
                        "dark_horse": 1.0,
                        "technical": 1.0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    Path(pred_path).write_text(
        json.dumps(predictions_store._default_data()),
        encoding="utf-8",
    )

    _orig_engine_init = learning_engine.LearningEngine.__init__

    @functools.wraps(_orig_engine_init)
    def _engine_init(self, soul_map_path="data/soul_map.json"):
        if soul_map_path == "data/soul_map.json":
            soul_map_path = soul_path
        _orig_engine_init(self, soul_map_path)

    _orig_bridge_init = mindmap_bridge.MindmapBridge.__init__

    @functools.wraps(_orig_bridge_init)
    def _bridge_init(self, persistence_path="data/soul_map.json", registry_path="config/registry.json"):
        if persistence_path == "data/soul_map.json":
            persistence_path = soul_path
        _orig_bridge_init(self, persistence_path, registry_path)

    monkeypatch.setattr(learning_engine.LearningEngine, "__init__", _engine_init)
    monkeypatch.setattr(mindmap_bridge.MindmapBridge, "__init__", _bridge_init)
    return soul_path


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


def test_readiness_uses_cache(monkeypatch):
    from internal.ops.readiness_cache import reset_readiness_cache

    reset_readiness_cache()
    import internal.ops.readiness_cache as cache

    calls = {"n": 0}

    def _fake_build():
        calls["n"] += 1
        return {"status": "ready", "ready": True, "issues": []}

    monkeypatch.setattr(cache, "TTL", 60.0)
    monkeypatch.setattr(cache, "BUILD_TIMEOUT", 2.0)
    with cache._CACHE_LOCK:
        cache._CACHE["at"] = time.time()
        cache._CACHE["payload"] = {"status": "ready", "ready": True, "issues": []}
    with patch("internal.ops.readiness.build_readiness_report", side_effect=_fake_build):
        with TestClient(app) as client:
            r1 = client.get("/api/ops/readiness")
            r2 = client.get("/api/ops/readiness")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r2.json().get("cached") is True
    assert calls["n"] == 0


def test_readiness_refresh_bypasses_cache(monkeypatch):
    from internal.ops.readiness_cache import reset_readiness_cache

    reset_readiness_cache()
    import internal.ops.readiness_cache as cache

    calls = {"n": 0}

    def _fake_build():
        calls["n"] += 1
        return {"status": "ready", "ready": True, "issues": []}

    monkeypatch.setattr(cache, "TTL", 60.0)
    with cache._CACHE_LOCK:
        cache._CACHE["at"] = time.time()
        cache._CACHE["payload"] = {"status": "ready", "ready": True, "issues": []}
    with patch("internal.ops.readiness.build_readiness_report", side_effect=_fake_build):
        with TestClient(app) as client:
            client.get("/api/ops/readiness")
            client.get("/api/ops/readiness?refresh=true")
    assert calls["n"] == 1


def test_readiness_timeout_serves_stale_primary(monkeypatch):
    """Under build timeout, return last good report — not a naked busy shell."""
    from internal.ops.readiness_cache import reset_readiness_cache

    reset_readiness_cache()
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

    monkeypatch.setattr(cache, "MAX_STALE_SECONDS", 9999.0)

    out = asyncio.run(_run())
    assert out.get("ready") is True
    assert out.get("serving_stale") is True
    assert out.get("cached") is True
    assert "readiness_build_slow" in (out.get("issues") or [])
    assert out.get("status") == "ready"


def test_readiness_busy_lock_does_not_block(monkeypatch):
    from internal.ops.readiness_cache import reset_readiness_cache

    reset_readiness_cache()
    import internal.ops.readiness_cache as cache

    with cache._BUILD_SLOT_LOCK:
        cache._ACTIVE_BUILD_GENERATION = 1
        cache._BUILD_GENERATION = 1
        cache._BUILD_STARTED_AT = time.time()
    try:
        with cache._CACHE_LOCK:
            cache._CACHE["at"] = time.time() - 120.0
            cache._CACHE["payload"] = {"status": "ready", "ready": True, "issues": []}
        out = cache._build_blocking(force=False)
        assert out.get("ready") is True
    finally:
        with cache._BUILD_SLOT_LOCK:
            cache._ACTIVE_BUILD_GENERATION = None


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


def test_resolve_true_requires_token_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("WRITE_API_TOKEN", "resolve-token")
    _isolate_learning_writes(tmp_path, monkeypatch)
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


def test_write_auth_browser_ux_posts_open_with_token_set(monkeypatch):
    """SimiVision chat and investigate stay public when WRITE_API_TOKEN is set."""
    monkeypatch.setenv("WRITE_API_TOKEN", "admin-token")
    monkeypatch.setattr(chat_service, "build_chat_context", lambda: {"source": "registry-fallback"})
    monkeypatch.setattr(chat_service, "_maybe_investigation_context", lambda _m: None)
    monkeypatch.setattr(
        chat_service,
        "call_llm",
        lambda *_a, **_k: ("Public UX ack.", True, "test-stub"),
    )
    monkeypatch.setattr(
        investigation_routes,
        "build_investigation_report",
        lambda *_a, **_k: {"status": "ok", "answer": "stub"},
    )
    with TestClient(app) as client:
        chat = client.post("/api/simivision/chat", json={"message": "public-ux"})
        assert chat.status_code == 200
        ask = client.post("/api/investigate/ask", json={"question": "public-ux"})
        assert ask.status_code == 200


def test_feedback_routes_require_token_when_enabled(monkeypatch, tmp_path):
    """Expert weight feedback POSTs require bearer when WRITE_API_TOKEN is set."""
    monkeypatch.setenv("WRITE_API_TOKEN", "admin-token")
    _isolate_learning_writes(tmp_path, monkeypatch)
    headers = {"Authorization": "Bearer admin-token"}
    with TestClient(app) as client:
        for path, body in (
            ("/api/mindmap/feedback", {"note": "public-ux"}),
            ("/api/feedback", {"feedback": "public-ux"}),
        ):
            denied = client.post(path, json=body)
            assert denied.status_code == 401, path
            ok = client.post(path, json=body, headers=headers)
            assert ok.status_code != 401, path


@pytest.mark.parametrize(
    "query",
    [
        "resolve=on",
        "resolve=t",
        "resolve=Y",
        "resolve=TRUE",
    ],
)
def test_resolve_truthy_spellings_require_token_when_enabled(monkeypatch, query):
    monkeypatch.setenv("WRITE_API_TOKEN", "resolve-token")
    with TestClient(app) as client:
        denied = client.get(f"/api/predictions/resolved?{query}")
    assert denied.status_code == 401


@pytest.mark.parametrize("query", ["resolve=false", "resolve=FALSE", "resolve=False"])
def test_resolve_false_stays_public_when_token_enabled(monkeypatch, query):
    monkeypatch.setenv("WRITE_API_TOKEN", "resolve-token")
    with TestClient(app) as client:
        r = client.get(f"/api/predictions/resolved?{query}")
    assert r.status_code == 200


def test_predictions_resolved_no_param_public_when_token_enabled(monkeypatch):
    monkeypatch.setenv("WRITE_API_TOKEN", "resolve-token")
    with TestClient(app) as client:
        r = client.get("/api/predictions/resolved")
    assert r.status_code == 200


def test_resolve_predictions_requires_token_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("WRITE_API_TOKEN", "resolve-token")
    _isolate_learning_writes(tmp_path, monkeypatch)
    headers = {"Authorization": "Bearer resolve-token"}
    with TestClient(app) as client:
        denied = client.get("/api/resolve-predictions")
        assert denied.status_code == 401
        ok = client.get("/api/resolve-predictions", headers=headers)
    assert ok.status_code != 401


def test_anonymous_feedback_post_does_not_change_weights(monkeypatch, tmp_path):
    """Decision 16: tokenless feedback must not nudge expert weights."""
    soul_path = _isolate_learning_writes(tmp_path, monkeypatch)
    monkeypatch.setenv("WRITE_API_TOKEN", "weight-guard-token")
    before = dict(load_weights(soul_path))
    with TestClient(app) as client:
        mindmap = client.post("/api/mindmap/feedback", json={"note": "anonymous-probe"})
        assert mindmap.status_code == 401
        feedback = client.post(
            "/api/feedback",
            json={
                "subnet_id": 1,
                "recommendation": "quant",
                "actual_performance": {"outcome": "neutral"},
            },
        )
        assert feedback.status_code == 401
    after = dict(load_weights(soul_path))
    assert before == after


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
