"""HTTP tests for /api/health (slice 14b)."""

from fastapi.testclient import TestClient

from server import app


def test_api_health_returns_ok_json():
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
