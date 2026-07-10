"""HTTP tests for the Oracle snapshot stub (slice 9)."""

from fastapi.testclient import TestClient

from server import app


def test_oracle_returns_snapshot():
    with TestClient(app) as client:
        response = client.get("/api/oracle")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in ("success", "stub")
    assert "data" in body
    assert isinstance(body["data"], list)
