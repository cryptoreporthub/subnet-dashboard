"""Resolver trigger guard when web serves HTTP only (issue #1631)."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from internal.council import resolver
from internal.rate_limit import get_limiter

_WRITE_TOKEN = "guard-test-token"
_AUTH_HEADERS = {"Authorization": f"Bearer {_WRITE_TOKEN}"}


@pytest.fixture(autouse=True)
def _sync_and_clear_rate_limit_counters():
    import server

    lim = get_limiter()
    if lim is not None and hasattr(server.app, "state"):
        server.app.state.limiter = lim
        lim.reset()
    yield
    lim = get_limiter()
    if lim is not None and hasattr(server.app, "state"):
        server.app.state.limiter = lim
        lim.reset()


def _test_client() -> TestClient:
    """Use live ``server.app`` so tests survive ``importlib.reload(server)`` in other modules."""
    import server

    return TestClient(server.app)


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


def _ensure_strict_limiter_active(monkeypatch) -> None:
    """Enable limiter with a clean singleton (safe after ``test_rate_limit`` reload)."""
    import internal.learning.routes as learning_routes
    import internal.rate_limit as rl
    import server

    monkeypatch.setenv("ENABLE_RATE_LIMIT", "1")
    monkeypatch.delenv("RATE_LIMIT_DEFAULT", raising=False)
    monkeypatch.setattr(rl, "_limiter", None)
    importlib.reload(learning_routes)
    importlib.reload(server)
    lim = get_limiter()
    if lim is None:
        pytest.fail("ENABLE_RATE_LIMIT=1 but limiter is unset")
    server.app.state.limiter = lim
    lim.reset()


def _restore_app_after_limit_reload(monkeypatch) -> None:
    """Undo server reload from strict-limit setup (keeps later tests on consistent app)."""
    import internal.learning.routes as learning_routes
    import internal.rate_limit as rl
    import server

    monkeypatch.setenv("ENABLE_RATE_LIMIT", "1")
    monkeypatch.delenv("RATE_LIMIT_DEFAULT", raising=False)
    monkeypatch.setattr(rl, "_limiter", None)
    importlib.reload(learning_routes)
    importlib.reload(server)
    lim = get_limiter()
    if lim is not None:
        server.app.state.limiter = lim
        lim.reset()


def test_learning_trigger_503_when_background_off_web(monkeypatch):
    _web_background_off(monkeypatch)
    res = _test_client().post("/api/learning/trigger", headers=_AUTH_HEADERS)
    assert res.status_code == 503
    assert "worker" in res.json()["detail"].lower()


def test_predictions_resolver_run_503_when_background_off_web(monkeypatch):
    _web_background_off(monkeypatch)
    res = _test_client().post("/api/predictions/resolver/run", headers=_AUTH_HEADERS)
    assert res.status_code == 503


def test_resolve_predictions_get_503_when_background_on_web_off(monkeypatch):
    _web_background_off(monkeypatch)
    calls = _count_resolve_calls(monkeypatch)
    res = _test_client().get("/api/resolve-predictions", headers=_AUTH_HEADERS)
    assert res.status_code == 503
    assert "worker" in res.json()["detail"].lower()
    assert calls["resolve_due"] == 0
    assert calls["load_pick"] == 0


def test_predictions_resolved_resolve_true_503_when_background_on_web_off(monkeypatch):
    _web_background_off(monkeypatch)
    calls = _count_resolve_calls(monkeypatch)
    monkeypatch.setattr(
        resolver,
        "get_resolved_predictions",
        lambda: {"resolved": [], "stats": {}},
    )
    client = _test_client()
    res = client.get("/api/predictions/resolved?resolve=true", headers=_AUTH_HEADERS)
    assert res.status_code == 503, res.text
    assert "worker" in res.json()["detail"].lower()
    assert calls["resolve_due"] == 0
    assert calls["load_pick"] == 0

    res_false = client.get("/api/predictions/resolved?resolve=false")
    assert res_false.status_code == 200
    assert res_false.json().get("status") == "ok"

    res_read = client.get("/api/predictions/resolved")
    assert res_read.status_code == 200
    assert res_read.json().get("status") == "ok"
    assert calls["resolve_due"] == 0
    assert calls["load_pick"] == 0


def test_resolver_gets_allowed_in_worker_mode(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "worker")
    monkeypatch.delenv("BACKGROUND_ON_WEB", raising=False)
    monkeypatch.setenv("WRITE_API_TOKEN", _WRITE_TOKEN)
    calls = _count_resolve_calls(monkeypatch)
    client = _test_client()
    r1 = client.get("/api/resolve-predictions", headers=_AUTH_HEADERS)
    assert r1.status_code == 200, r1.text
    r2 = client.get("/api/predictions/resolved?resolve=true", headers=_AUTH_HEADERS)
    assert r2.status_code == 200, r2.text
    assert calls["resolve_due"] == 2
    assert calls["load_pick"] == 2


def test_resolver_gets_allowed_when_background_on_web_on(monkeypatch):
    _resolver_allowed_env(monkeypatch)
    calls = _count_resolve_calls(monkeypatch)
    client = _test_client()
    r1 = client.get("/api/resolve-predictions", headers=_AUTH_HEADERS)
    assert r1.status_code == 200, r1.text
    r2 = client.get("/api/predictions/resolved?resolve=true", headers=_AUTH_HEADERS)
    assert r2.status_code == 200, r2.text
    assert calls["resolve_due"] == 2
    assert calls["load_pick"] == 2


def test_predictions_resolved_reads_default_limit_resolve_true_strict(monkeypatch):
    """Read-only polls keep default limit; only resolve=true hits strict 30/min."""
    import internal.learning.routes as learning_routes

    _resolver_allowed_env(monkeypatch)
    _count_resolve_calls(monkeypatch)
    _ensure_strict_limiter_active(monkeypatch)
    try:
        monkeypatch.setattr(learning_routes, "load_weights", lambda: {})
        client = _test_client()
        for i in range(35):
            res = client.get("/api/predictions/resolved")
            assert res.status_code == 200, f"read {i + 1}: {res.text}"

        for i in range(30):
            res = client.get("/api/predictions/resolved?resolve=true", headers=_AUTH_HEADERS)
            assert res.status_code == 200, f"resolve {i + 1}: {res.text}"
        res = client.get("/api/predictions/resolved?resolve=true", headers=_AUTH_HEADERS)
        assert res.status_code == 429
    finally:
        _restore_app_after_limit_reload(monkeypatch)


def test_resolve_predictions_get_strict_rate_limit_31st_429(monkeypatch):
    """GET /api/resolve-predictions is resolve-only — strict limit on whole route."""
    import internal.learning.routes as learning_routes

    _resolver_allowed_env(monkeypatch)
    _count_resolve_calls(monkeypatch)
    _ensure_strict_limiter_active(monkeypatch)
    try:
        monkeypatch.setattr(learning_routes, "load_weights", lambda: {})
        client = _test_client()
        for i in range(30):
            res = client.get("/api/resolve-predictions", headers=_AUTH_HEADERS)
            assert res.status_code == 200, f"request {i + 1}: {res.text}"
        res = client.get("/api/resolve-predictions", headers=_AUTH_HEADERS)
        assert res.status_code == 429
    finally:
        _restore_app_after_limit_reload(monkeypatch)
