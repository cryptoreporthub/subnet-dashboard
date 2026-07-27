"""Resolver trigger guard when web serves HTTP only."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server import app


def test_learning_trigger_503_when_background_off_web(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("BACKGROUND_ON_WEB", "off")
    monkeypatch.delenv("INLINE_WORKER", raising=False)
    client = TestClient(app)
    res = client.post("/api/learning/trigger")
    assert res.status_code == 503
    assert "worker" in res.json()["detail"].lower()


def test_predictions_resolver_run_503_when_background_off_web(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("BACKGROUND_ON_WEB", "off")
    client = TestClient(app)
    res = client.post("/api/predictions/resolver/run")
    assert res.status_code == 503
