"""Resolver trigger guard when web serves HTTP only (issue #1631)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from internal.council import resolver
from internal.learning import routes as learning_routes
from internal.rate_limit import get_limiter, rate_limit_enabled
from server import app

_WRITE_TOKEN = "guard-test-token"
_AUTH_HEADERS = {"Authorization": f"Bearer {_WRITE_TOKEN}"}


def _count_resolve_calls(monkeypatch) -> dict[str, int]:
    calls = {"resolve_due": 0, "load_pick": 0}

    def _spy_resolve(*_a, **_k):
        calls["resolve_due"] += 1
        return {"resolved": [], "stats": {}, "pending": []}

    def _spy_pick():
        calls["load_pick"] += 1
        return []

    import internal.subnets.feed as feed

    monkeypatch.setattr(resolver, "resolve_due_predictions", _spy_resolve)
    monkeypatch.setattr(feed, "load_pick_subnets", _spy_pick)
    return calls


def _web_background_off(monkeypatch) -> None:
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("BACKGROUND_ON_WEB", "off")
    monkeypatch.delenv("INLINE_WORKER", raising=False)
    monkeypatch.setenv("WRITE_API_TOKEN", _WRITE_TOKEN)


def _resolver_allowed_env(monkeypatch) -> None:
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("BACKGROUND_ON_WEB", "on")
    monkeypatch.setenv("WRITE_API_TOKEN", _WRITE_TOKEN)


def test_learning_trigger_503_when_background_off_web(monkeypatch):
    _web_background_off(monkeypatch)
    client = TestClient(app)
    res = client.post("/api/learning/trigger", headers=_AUTH_HEADERS)
    assert res.status_code == 503
    assert "worker" in res.json()["detail"].lower()


def test_predictions_resolver_run_503_when_background_off_web(monkeypatch):
    _web_background_off(monkeypatch)
    client = TestClient(app)
    res = client.post("/api/predictions/resolver/run", headers=_AUTH_HEADERS)
    assert res.status_code == 503


def test_resolve_predictions_get_503_when_background_on_web_off(monkeypatch):
    _web_background_off(monkeypatch)
    calls = _count_resolve_calls(monkeypatch)
    client = TestClient(app)
    res = client.get("/api/resolve-predictions", headers=_AUTH_HEADERS)
    assert res.status_code == 503
    assert "worker" in res.json()["detail"].lower()
    assert calls["resolve_due"] == 0


def test_predictions_resolved_resolve_true_503_when_background_on_web_off(monkeypatch):
    _web_background_off(monkeypatch)
    calls = _count_resolve_calls(monkeypatch)
    monkeypatch.setattr(
        resolver,
        "get_resolved_predictions",
        lambda: {"resolved": [], "stats": {}},
    )
    client = TestClient(app)
    res = client.get("/api/predictions/resolved?resolve=true", headers=_AUTH_HEADERS)
    assert res.status_code == 503, res.text
    assert "worker" in res.json()["detail"].lower()
    assert calls["resolve_due"] == 0

    res_false = client.get("/api/predictions/resolved?resolve=false")
    assert res_false.status_code == 200
    assert res_false.json().get("status") == "ok"

    res_read = client.get("/api/predictions/resolved")
    assert res_read.status_code == 200
    assert res_read.json().get("status") == "ok"
    assert calls["resolve_due"] == 0


def test_resolver_gets_allowed_in_worker_mode(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.delenv("BACKGROUND_ON_WEB", raising=False)
    monkeypatch.setenv("WRITE_API_TOKEN", _WRITE_TOKEN)
    calls = _count_resolve_calls(monkeypatch)
    client = TestClient(app)
    r1 = client.get("/api/resolve-predictions", headers=_AUTH_HEADERS)
    assert r1.status_code == 200, r1.text
    r2 = client.get("/api/predictions/resolved?resolve=true", headers=_AUTH_HEADERS)
    assert r2.status_code == 200, r2.text
    assert calls["resolve_due"] == 2
    assert calls["load_pick"] == 2


def test_resolver_gets_allowed_when_background_on_web_on(monkeypatch):
    _resolver_allowed_env(monkeypatch)
    calls = _count_resolve_calls(monkeypatch)
    client = TestClient(app)
    r1 = client.get("/api/resolve-predictions", headers=_AUTH_HEADERS)
    assert r1.status_code == 200, r1.text
    r2 = client.get("/api/predictions/resolved?resolve=true", headers=_AUTH_HEADERS)
    assert r2.status_code == 200, r2.text
    assert calls["resolve_due"] == 2
    assert calls["load_pick"] == 2


@pytest.mark.parametrize(
    "path",
    [
        "/api/resolve-predictions",
        "/api/predictions/resolved?resolve=true",
    ],
)
def test_resolver_get_strict_rate_limit_31st_request_429(monkeypatch, path):
    """31st resolver GET in a minute returns 429 (matches POST strict 30/minute)."""
    if not rate_limit_enabled() or get_limiter() is None:
        pytest.skip("rate limiter no-op (ENABLE_RATE_LIMIT=0 or limiter unset)")
    if not hasattr(learning_routes.api_resolve_predictions, "__wrapped__"):
        pytest.fail("GET /api/resolve-predictions missing @limit_or_noop(strict_limit)")
    if not hasattr(learning_routes.api_predictions_resolved, "__wrapped__"):
        pytest.fail("GET /api/predictions/resolved missing @limit_or_noop(strict_limit)")

    import internal.rate_limit as rl

    _resolver_allowed_env(monkeypatch)
    _count_resolve_calls(monkeypatch)
    monkeypatch.setattr(learning_routes, "load_weights", lambda: {})
    rl._limiter = None
    assert get_limiter() is not None

    client_ip = "203.0.113.50" if "resolve-predictions" in path else "203.0.113.51"
    headers = {**_AUTH_HEADERS, "X-Forwarded-For": client_ip}

    client = TestClient(app)
    for i in range(30):
        res = client.get(path, headers=headers)
        assert res.status_code != 429, f"request {i + 1} got 429 early: {res.text}"
    res = client.get(path, headers=headers)
    assert res.status_code == 429