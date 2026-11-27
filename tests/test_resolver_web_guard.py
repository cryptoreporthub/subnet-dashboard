"""Resolver trigger guard when web serves HTTP only (issue #1631)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from internal.council import resolver
from server import app

_WRITE_TOKEN = "guard-test-token"
_AUTH_HEADERS = {"Authorization": f"Bearer {_WRITE_TOKEN}"}


def _count_resolve_calls(monkeypatch) -> dict[str, int]:
    calls = {"resolve_due": 0}

    def _spy(*_a, **_k):
        calls["resolve_due"] += 1
        return {"resolved": [], "stats": {}, "pending": []}

    monkeypatch.setattr(resolver, "resolve_due_predictions", _spy)
    return calls


def _web_background_off(monkeypatch) -> None:
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("BACKGROUND_ON_WEB", "off")
    monkeypatch.delenv("INLINE_WORKER", raising=False)
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


def test_resolver_gets_allowed_when_background_on_web_on(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("BACKGROUND_ON_WEB", "on")
    monkeypatch.setenv("WRITE_API_TOKEN", _WRITE_TOKEN)
    calls = _count_resolve_calls(monkeypatch)
    client = TestClient(app)
    r1 = client.get("/api/resolve-predictions", headers=_AUTH_HEADERS)
    assert r1.status_code == 200, r1.text
    r2 = client.get("/api/predictions/resolved?resolve=true", headers=_AUTH_HEADERS)
    assert r2.status_code == 200, r2.text
    assert calls["resolve_due"] == 2