"""Resolver state endpoint stays useful when the cross-process probe fails."""

from __future__ import annotations

from fastapi.testclient import TestClient

from internal.learning import routes as learning_routes
from server import app


def test_resolver_state_error_returns_bounded_memory_fallback(monkeypatch):
    async def _boom(*_args, **_kwargs):
        raise RuntimeError("volume unavailable")

    monkeypatch.setattr(learning_routes, "_to_thread_timeout", _boom)
    monkeypatch.setattr(
        learning_routes,
        "get_prediction_resolver_scheduler_state",
        lambda: {"running": False, "last_run_at": None},
    )

    response = TestClient(app).get("/api/predictions/resolver")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["source"] == "memory"
    assert body["data"]["error"] == "state_unavailable"
    assert body["data"]["running"] is False