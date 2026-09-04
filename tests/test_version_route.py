"""GET /version deploy-receipt route."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server import app


def test_version_route_returns_200_with_version_key(monkeypatch):
    monkeypatch.setenv("DISABLE_BACKGROUND_SCANS", "1")
    monkeypatch.setenv("SENTRY_RELEASE", "abcdef0123456789deadbeef")
    with TestClient(app) as client:
        response = client.get("/version")
    assert response.status_code == 200
    assert response.headers.get("content-type", "").startswith("application/json")
    body = response.json()
    assert "version" in body
    assert body["version"] == "abcdef0"
    assert body["sentry_release"] == "abcdef0123456789deadbeef"
    assert body["python"]
    assert isinstance(body["python"], str)


def test_version_route_unknown_when_env_missing(monkeypatch):
    monkeypatch.setenv("DISABLE_BACKGROUND_SCANS", "1")
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    with TestClient(app) as client:
        response = client.get("/version")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "unknown"
    assert body["sentry_release"] == ""
    assert "python" in body


def test_version_route_unknown_when_sentry_release_unknown(monkeypatch):
    monkeypatch.setenv("DISABLE_BACKGROUND_SCANS", "1")
    monkeypatch.setenv("SENTRY_RELEASE", "unknown")
    with TestClient(app) as client:
        response = client.get("/version")
    assert response.status_code == 200
    assert response.json()["version"] == "unknown"
