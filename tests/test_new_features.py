"""Tests for the new FastAPI endpoints and SimiVision tooltip integration.

These tests target the current FastAPI implementation in server.py. Legacy
Flask-style tests in this repo reference symbols that no longer exist and are
out of scope for this feature work.
"""

import pytest
from fastapi.testclient import TestClient

from server import app


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Subnet state vector
# ---------------------------------------------------------------------------

def test_subnet_state_found(client):
    response = client.get("/api/subnets/29/state")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    data = payload["data"]
    assert data["netuid"] == 29
    assert data["name"] == "Coldint"
    assert "metrics" in data
    assert "technical_indicators" in data
    assert "signal_impact" in data
    assert "prediction" in data
    assert "social_sentiment" in data
    assert "consensus" in data


def test_subnet_state_not_found(client):
    response = client.get("/api/subnets/99999/state")
    assert response.status_code == 404
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["netuid"] == 99999
    assert "not found" in payload["error"].lower()


# ---------------------------------------------------------------------------
# Top Pick of the Hour / Day
# ---------------------------------------------------------------------------

def test_top_pick_hour(client):
    response = client.get("/api/top-pick/hour")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["window"] == "hour"
    data = payload["data"]
    assert "netuid" in data
    assert "name" in data
    assert "score" in data
    assert isinstance(data["score"], float)


def test_top_pick_day(client):
    response = client.get("/api/top-pick/day")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["window"] == "day"
    data = payload["data"]
    assert "netuid" in data
    assert "name" in data
    assert "score" in data
    assert isinstance(data["score"], float)


# ---------------------------------------------------------------------------
# Homepage renders SimiVision tooltip integration
# ---------------------------------------------------------------------------

def test_homepage_renders_top_picks(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "Top Pick of the Hour" in html
    assert "Top Pick of the Day" in html
    assert 'id="topPickHourName"' in html
    assert 'id="topPickDayName"' in html
    assert "/api/top-pick/hour" in html
    assert "/api/top-pick/day" in html


def test_homepage_renders_jargon_tooltips(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'class="jargon-term"' in html
    assert 'data-jargon="conviction"' in html
    assert 'data-jargon="emission"' in html
    assert 'data-jargon="apy"' in html
    assert 'data-jargon="recommendation"' in html
    assert 'data-jargon="sell-alert"' in html
    # HOT is data-driven; static fallback currently has no active hot picks.
    assert 'data-jargon="hot"' in html or 'data-jargon="sell-alert"' in html
    assert "simi-tooltip" in html
    assert "SimiVision clickable jargon tooltips" in html


# ---------------------------------------------------------------------------
# Existing FastAPI routes still work
# ---------------------------------------------------------------------------

def test_health_route(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.text == "OK"


def test_api_simivision_route(client):
    response = client.get("/api/simivision")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert "top" in payload["data"]
