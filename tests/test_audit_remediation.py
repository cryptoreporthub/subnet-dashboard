"""Audit remediation P0/P1 — readiness cache, write auth, webhook SSRF guard."""

from __future__ import annotations

import functools
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Mount

import internal.council.mindmap_bridge as mindmap_bridge
import internal.council.resolver as resolver
import internal.council.resolver_scheduler as resolver_scheduler
import internal.council.weights as weights
import internal.investigation.routes as investigation_routes
import internal.signals.alerts as alerts_mod
import internal.signals.routes as signals_routes
import internal.simivision.chat_service as chat_service
import server as server_mod
from datastore import learning_engine
from internal.council.weights import load_weights
from internal.learning import predictions_store
from internal.write_auth import _PUBLIC_WRITE_EXACT
from server import app

_WRITE_HTTP_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


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


def _isolate_alerts_store(tmp_path, monkeypatch) -> str:
    alerts_path = str(tmp_path / "alerts.json")
    Path(alerts_path).write_text(
        json.dumps({"updated_at": None, "alerts": []}),
        encoding="utf-8",
    )
    subs_path = str(tmp_path / "alert_subscriptions.json")
    Path(subs_path).write_text('{"webhooks": []}', encoding="utf-8")
    monkeypatch.setenv("ALERTS_PATH", alerts_path)
    monkeypatch.setenv("ALERT_SUBSCRIPTIONS_PATH", subs_path)
    monkeypatch.setattr(alerts_mod, "ALERTS_PATH", alerts_path)
    signals_routes._alerts = None
    return alerts_path


def _block_weight_mutations(monkeypatch) -> dict[str, int]:
    calls = {"resolve": 0, "nudge": 0}

    def _resolve_blocked(*_a, **_k):
        calls["resolve"] += 1
        return {"resolved": [], "stats": {}}

    def _nudge_blocked(*_a, **_k):
        calls["nudge"] += 1
        return 1.0

    monkeypatch.setattr(resolver, "resolve_due_predictions", _resolve_blocked)
    monkeypatch.setattr(weights, "nudge_expert", _nudge_blocked)
    return calls


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
    calls = _block_weight_mutations(monkeypatch)
    with TestClient(app) as client:
        denied = client.get("/api/predictions/resolved?resolve=true")
        assert denied.status_code == 401
        assert calls["resolve"] == 0
        assert calls["nudge"] == 0
        ok = client.get(
            "/api/predictions/resolved?resolve=true",
            headers={"Authorization": "Bearer resolve-token"},
        )
    assert ok.status_code == 200
    assert calls["resolve"] == 1


def test_write_auth_default_deny_admin_posts(monkeypatch, tmp_path):
    """Admin/state mutations require bearer when token is set."""
    _isolate_alerts_store(tmp_path, monkeypatch)
    monkeypatch.setenv("DISABLE_BACKGROUND_SCANS", "1")
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("BACKGROUND_ON_WEB", "off")
    monkeypatch.delenv("INLINE_WORKER", raising=False)
    resolver_scheduler.stop_prediction_resolver_scheduler()
    monkeypatch.setenv("WRITE_API_TOKEN", "admin-token")
    headers = {"Authorization": "Bearer admin-token"}
    alert_body = {"alert_type": "manual", "message": "t", "severity": "info"}
    client = TestClient(app)
    try:
        assert client.post("/api/learning/trigger", json={}).status_code == 401
        assert client.post("/api/predictions/resolver/run", json={}).status_code == 401
        assert client.post("/api/alerts", json=alert_body).status_code == 401
        assert (
            client.post("/api/learning/trigger", json={}, headers=headers).status_code == 503
        )
        assert (
            client.post("/api/predictions/resolver/run", json={}, headers=headers).status_code
            == 503
        )
        assert client.post("/api/alerts", json=alert_body, headers=headers).status_code == 201
    finally:
        client.close()


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
    calls = _block_weight_mutations(monkeypatch)
    headers = {"Authorization": "Bearer admin-token"}
    with TestClient(app) as client:
        for path, body in (
            ("/api/mindmap/feedback", {"note": "public-ux"}),
            ("/api/feedback", {"feedback": "public-ux"}),
        ):
            denied = client.post(path, json=body)
            assert denied.status_code == 401, path
    assert calls["nudge"] == 0
    weight_payload = {
        "subnet_id": 1,
        "recommendation": "quant",
        "actual_performance": {"outcome": "neutral", "correct_prediction": True},
    }
    with TestClient(app) as client:
        ok_mindmap = client.post(
            "/api/mindmap/feedback",
            json={"note": "public-ux"},
            headers=headers,
        )
        ok_feedback = client.post(
            "/api/feedback",
            json=weight_payload,
            headers=headers,
        )
    assert ok_mindmap.status_code == 200
    assert ok_feedback.status_code == 200


@pytest.mark.parametrize(
    "query",
    [
        "resolve=on",
        "resolve=t",
        "resolve=Y",
        "resolve=TRUE",
    ],
)
def test_resolve_truthy_spellings_require_token_when_enabled(monkeypatch, query, tmp_path):
    monkeypatch.setenv("WRITE_API_TOKEN", "resolve-token")
    _isolate_learning_writes(tmp_path, monkeypatch)
    calls = _block_weight_mutations(monkeypatch)
    with TestClient(app) as client:
        denied = client.get(f"/api/predictions/resolved?{query}")
    assert denied.status_code == 401
    assert calls["resolve"] == 0
    assert calls["nudge"] == 0


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
    calls = _block_weight_mutations(monkeypatch)
    headers = {"Authorization": "Bearer resolve-token"}
    with TestClient(app) as client:
        denied = client.get("/api/resolve-predictions")
        assert denied.status_code == 401
        assert calls["resolve"] == 0
        assert calls["nudge"] == 0
        ok = client.get("/api/resolve-predictions", headers=headers)
    assert ok.status_code == 200
    assert calls["resolve"] == 1


def test_anonymous_feedback_post_does_not_change_weights(monkeypatch, tmp_path):
    """Decision 16: tokenless feedback must not nudge expert weights."""
    soul_path = _isolate_learning_writes(tmp_path, monkeypatch)
    calls = _block_weight_mutations(monkeypatch)
    monkeypatch.setenv("WRITE_API_TOKEN", "weight-guard-token")
    weight_payload = {
        "subnet_id": 1,
        "recommendation": "quant",
        "actual_performance": {"outcome": "neutral", "correct_prediction": True},
    }
    before = dict(load_weights(soul_path))
    with TestClient(app) as client:
        mindmap = client.post("/api/mindmap/feedback", json={"note": "anonymous-probe"})
        assert mindmap.status_code == 401
        feedback = client.post("/api/feedback", json=weight_payload)
        assert feedback.status_code == 401
    assert calls["nudge"] == 0
    after = dict(load_weights(soul_path))
    assert before == after


def test_feedback_routes_denied_never_nudge(monkeypatch, tmp_path):
    monkeypatch.setenv("WRITE_API_TOKEN", "admin-token")
    _isolate_learning_writes(tmp_path, monkeypatch)
    calls = _block_weight_mutations(monkeypatch)
    with TestClient(app) as client:
        client.post(
            "/api/feedback",
            json={
                "subnet_id": 1,
                "recommendation": "quant",
                "actual_performance": {"correct_prediction": True},
            },
        )
        client.post("/api/mindmap/feedback", json={"note": "x"})
    assert calls["nudge"] == 0
    assert calls["resolve"] == 0


def test_write_auth_accepts_x_write_api_token_header(monkeypatch, tmp_path):
    monkeypatch.setenv("WRITE_API_TOKEN", "header-token")
    _isolate_learning_writes(tmp_path, monkeypatch)
    calls = _block_weight_mutations(monkeypatch)
    with TestClient(app) as client:
        r = client.get(
            "/api/resolve-predictions",
            headers={"X-Write-Api-Token": "header-token"},
        )
    assert r.status_code == 200
    assert calls["resolve"] == 1


def test_write_auth_resolve_predictions_trailing_slash_requires_token(monkeypatch):
    monkeypatch.setenv("WRITE_API_TOKEN", "slash-token")
    calls = _block_weight_mutations(monkeypatch)
    with TestClient(app) as client:
        r = client.get("/api/resolve-predictions/", follow_redirects=False)
    assert r.status_code == 401
    assert calls["resolve"] == 0


def test_write_auth_resolve_predictions_head_requires_token(monkeypatch):
    monkeypatch.setenv("WRITE_API_TOKEN", "head-token")
    calls = _block_weight_mutations(monkeypatch)
    with TestClient(app) as client:
        r = client.head("/api/resolve-predictions")
    assert r.status_code == 401
    assert calls["resolve"] == 0


def test_write_auth_protected_under_root_path_prefix(monkeypatch):
    monkeypatch.setenv("WRITE_API_TOKEN", "root-token")
    calls = _block_weight_mutations(monkeypatch)
    with TestClient(app, root_path="/mcp") as client:
        r = client.get("/mcp/api/resolve-predictions")
        r2 = client.get("/mcp/api/predictions/resolved?resolve=true")
    assert r.status_code == 401
    assert r2.status_code == 401
    assert calls["resolve"] == 0


def test_write_auth_import_guard_raises_when_token_set(monkeypatch):
    monkeypatch.setenv("WRITE_API_TOKEN", "configured")
    with pytest.raises(RuntimeError, match="boom"):
        server_mod._write_auth_import_guard(RuntimeError("boom"))


def test_write_auth_import_guard_no_raise_when_token_unset(monkeypatch):
    monkeypatch.delenv("WRITE_API_TOKEN", raising=False)
    server_mod._write_auth_import_guard(RuntimeError("boom"))


def test_write_auth_non_ascii_bearer_returns_401_not_500(monkeypatch):
    """Non-ASCII bearer must not bubble up as compare_digest UnicodeEncodeError (500)."""
    from starlette.requests import Request

    from internal.write_auth import check_write_auth

    monkeypatch.setenv("WRITE_API_TOKEN", "ascii-token")
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/api/resolve-predictions",
        "raw_path": b"/api/resolve-predictions",
        "query_string": b"",
        "headers": [(b"authorization", "Bearer café".encode("utf-8"))],
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "root_path": "",
    }
    denied = check_write_auth(Request(scope))
    assert denied is not None
    assert denied.status_code == 401


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_write_auth_middleware_import_fail_closed_subprocess():
    """Mutant I: missing write_auth module must abort server import when token is set."""
    env = {
        **os.environ,
        "PYTHONPATH": str(_repo_root()),
        "DISABLE_BACKGROUND_SCANS": "1",
        "WRITE_API_TOKEN": "probe-token",
    }
    fail_code = (
        "import sys\n"
        "sys.modules['internal.write_auth'] = None\n"
        "try:\n"
        "    import server\n"
        "except Exception:\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(42)\n"
    )
    fail = subprocess.run(
        [sys.executable, "-c", fail_code],
        cwd=_repo_root(),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert fail.returncode == 0, fail.stderr[-500:] if fail.stderr else fail.stdout[-500:]

    ok_env = {**os.environ, "PYTHONPATH": str(_repo_root()), "DISABLE_BACKGROUND_SCANS": "1"}
    ok_env.pop("WRITE_API_TOKEN", None)
    ok_code = (
        "import sys\n"
        "sys.modules['internal.write_auth'] = None\n"
        "import server\n"
    )
    ok = subprocess.run(
        [sys.executable, "-c", ok_code],
        cwd=_repo_root(),
        env=ok_env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert ok.returncode == 0, ok.stderr[-800:] if ok.stderr else ok.stdout[-800:]


def _collect_nonpublic_write_routes(routes, prefix: str = "") -> list[tuple[str, str]]:
    collected: list[tuple[str, str]] = []
    for route in routes:
        if isinstance(route, Mount):
            mount = route.path.rstrip("/")
            collected.extend(_collect_nonpublic_write_routes(route.routes, prefix + mount))
            continue
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        full_path = f"{prefix}{path}"
        if "{" in full_path:
            continue
        for method in methods:
            if method in _WRITE_HTTP_METHODS and full_path not in _PUBLIC_WRITE_EXACT:
                collected.append((method, full_path))
    return collected


def test_write_auth_invariant_nonpublic_writes_require_token(monkeypatch):
    """Every non-allowlisted write route returns 401 without bearer when token is set."""
    monkeypatch.setenv("WRITE_API_TOKEN", "invariant-token")
    failures: list[str] = []
    seen: set[tuple[str, str]] = set()
    with TestClient(app) as client:
        for method, path in _collect_nonpublic_write_routes(app.routes):
            key = (method, path)
            if key in seen:
                continue
            seen.add(key)
            if method == "POST":
                r = client.post(path, json={})
            elif method == "PUT":
                r = client.put(path, json={})
            elif method == "PATCH":
                r = client.patch(path, json={})
            else:
                r = client.delete(path)
            if r.status_code != 401:
                failures.append(f"{method} {path} -> {r.status_code}")
    assert not failures, "write_auth gaps (fix in write_auth.py or list):\n" + "\n".join(
        failures[:40]
    )


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
