"""HTTP tests for the technical indicator read routes (slice 7)."""

from fastapi.testclient import TestClient

from server import app


def test_indicators_returns_persisted_state():
    with TestClient(app) as client:
        response = client.get("/api/indicators")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert isinstance(body["data"], dict)


def test_indicators_scheduler_returns_state():
    with TestClient(app) as client:
        response = client.get("/api/indicators/scheduler")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert "running" in body["data"]


def test_indicators_convergence_returns_subnet_rows():
    with TestClient(app) as client:
        response = client.get("/api/indicators-convergence")
    assert response.status_code == 200
    body = response.json()
    assert "subnets" in body
    assert isinstance(body["subnets"], list)
    if body["subnets"]:
        row = body["subnets"][0]
        assert "netuid" in row
        assert "oversold" in row
        assert "overbought" in row
