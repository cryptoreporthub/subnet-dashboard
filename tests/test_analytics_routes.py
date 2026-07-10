"""HTTP tests for pump analytics and price-tracking routes (slice 10b)."""

from fastapi.testclient import TestClient

from server import app


def test_pump_analytics_returns_payload():
    with TestClient(app) as client:
        response = client.get("/api/pump-analytics")
    assert response.status_code == 200
    body = response.json()
    assert "data" in body
    assert "subnets" in body["data"]
    assert "meta" in body["data"]


def test_price_tracking_baselines_empty_ok():
    with TestClient(app) as client:
        response = client.get("/api/price-tracking/baselines")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert "baselines" in body


def test_price_tracking_outcomes_degrades_gracefully():
    with TestClient(app) as client:
        response = client.get("/api/price-tracking/outcomes")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert "outcomes" in body
