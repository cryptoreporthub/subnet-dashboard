import pytest
from fastapi.testclient import TestClient

from server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health_route(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.text == "OK"


def test_api_simivision_route(client):
    response = client.get("/api/simivision")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "data" in data


def test_api_top_picks(client):
    response = client.get("/api/top-picks")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "data_source" in data
    picks = data["data"]
    assert "hour" in picks
    assert "day" in picks
    for key in ("hour", "day"):
        pick = picks[key]
        if pick is None:
            continue
        assert "netuid" in pick
        assert "name" in pick
        assert "score" in pick
        assert isinstance(pick["netuid"], int)
        assert isinstance(pick["name"], str)
        assert isinstance(pick["score"], (int, float))


def test_subnet_state_found(client):
    # Discover a known netuid from the subnets list
    subnets_response = client.get("/api/subnets")
    assert subnets_response.status_code == 200
    subnets = subnets_response.json()["subnets"]
    assert subnets, "No subnets available to test state endpoint"
    netuid = subnets[0]["netuid"]

    response = client.get(f"/api/subnets/{netuid}/state")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "data_source" in data
    vector = data["data"]
    assert vector["netuid"] == netuid
    assert "name" in vector
    assert "status" in vector
    assert "sector" in vector
    assert "metrics" in vector
    assert "technical_indicators" in vector
    assert "convergence" in vector
    assert "hot" in vector
    assert "sell" in vector
    assert "signal_impact" in vector
    assert "prediction" in vector
    assert "social_sentiment" in vector
    assert "consensus" in vector
    assert "timestamp" in vector
    assert "action" in vector["consensus"]
    assert "score" in vector["consensus"]


def test_subnet_state_not_found(client):
    response = client.get("/api/subnets/999999/state")
    assert response.status_code == 404
    data = response.json()
    assert data["status"] == "error"
    assert "error" in data


def test_separate_jargon_assets(client):
    # Static files exist and are served
    css_response = client.get("/static/css/simivision_jargon.css")
    js_response = client.get("/static/js/simivision_jargon.js")
    assert css_response.status_code == 200
    assert js_response.status_code == 200
    assert ".jargon-term" in css_response.text
    assert ".simi-tooltip" in css_response.text
    assert "GLOSSARY" in js_response.text
    assert "applyJargonTooltips" in js_response.text

    # Homepage references the new assets
    home_response = client.get("/")
    assert home_response.status_code == 200
    html = home_response.text
    assert "/static/css/simivision_jargon.css" in html
    assert "/static/js/simivision_jargon.js" in html
