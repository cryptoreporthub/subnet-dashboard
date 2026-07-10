"""Smoke tests for the FastAPI server entry point."""

import pytest
from fastapi.testclient import TestClient

from server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_route(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.text in ("OK", "ok")


def test_api_health_route(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") in ("ok", "OK", "success", "healthy")


def test_subnets_route(client):
    response = client.get("/api/subnets?limit=2")
    assert response.status_code == 200
    data = response.json()
    assert "subnets" in data or isinstance(data, list)


def test_top_picks_route(client):
    response = client.get("/api/top-picks")
    assert response.status_code == 200
    data = response.json()
    assert "hour_picks" in data
    assert "day_picks" in data


def test_ruggers_summary_route(client):
    response = client.get("/api/ruggers/summary")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "success"
    assert "stats" in data


def test_ruggers_watchlist_route(client):
    response = client.get("/api/ruggers/watchlist")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "success"
    assert "watchlist" in data


def test_cors_headers(client):
    response = client.get("/api/subnets", headers={"Origin": "https://example.com"})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "*"


def test_index_route(client):
    response = client.get("/")
    assert response.status_code == 200
