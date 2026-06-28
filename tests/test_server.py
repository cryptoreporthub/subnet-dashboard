import pytest
import json
from fastapi.testclient import TestClient
from server import app, _app_version

@pytest.fixture
def client():
    return TestClient(app)

def test_index_route(client):
    response = client.get('/')
    assert response.status_code == 200
    html = response.text
    assert 'Subnet Dashboard' in html or 'SimiVision' in html


def test_subnets_list_route(client):
    response = client.get('/api/subnets?status=active&sort=emission&order=desc&limit=2')
    assert response.status_code == 200
    data = response.json()
    assert 'subnets' in data


def test_health_route(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert response.text == "OK"


def test_top_pick_day_route(client):
    response = client.get('/api/top-pick/day')
    assert response.status_code == 200
    data = response.json()
    assert 'picks' in data


def test_top_pick_hour_route(client):
    response = client.get('/api/top-pick/hour')
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list) or 'picks' in data


def test_daily_pick_route(client):
    response = client.get('/api/daily-pick')
    assert response.status_code == 200
    data = response.json()
    assert 'pick' in data or 'picks' in data


def test_simivision_route(client):
    response = client.get('/api/simivision')
    assert response.status_code == 200
    data = response.json()
    assert 'signals' in data or 'choices' in data or 'data' in data


def test_rotation_tokens_route(client):
    response = client.get('/api/rotation-tokens')
    assert response.status_code == 200
    data = response.json()
    assert 'tokens' in data or 'rotation' in data or 'data' in data


def test_mindmap_summary_route(client):
    response = client.get('/api/mindmap/summary')
    assert response.status_code == 200
    data = response.json()
    payload = data.get('data', data)
    assert 'expert_weights' in payload
    weights = payload['expert_weights']
    assert any(k in weights for k in ('quant', 'hype', 'contrarian', 'technical'))


def test_learning_stats_route(client):
    response = client.get('/api/learning/stats')
    assert response.status_code == 200
    data = response.json()
    payload = data.get('data', data)
    assert 'expert_weights' in payload
    assert 'last_updated' in payload
    assert any(k in payload['expert_weights'] for k in ('quant', 'hype', 'contrarian', 'technical'))


def test_predictions_route(client):
    response = client.get('/api/predictions')
    assert response.status_code == 200
    data = response.json()
    assert 'predictions' in data or 'data' in data


def test_scenario_memory_route(client):
    response = client.get('/api/scenario-memory')
    assert response.status_code == 200
    data = response.json()
    assert 'scenarios' in data or 'data' in data


def test_rotation_tracker_route(client):
    response = client.get('/api/rotation-tracker')
    assert response.status_code == 200
    data = response.json()
    assert 'patterns' in data or 'data' in data


def test_learning_metrics_route(client):
    response = client.get('/api/learning-metrics')
    assert response.status_code == 200
    data = response.json()
    assert 'expert_weights' in data or 'metrics' in data or 'data' in data


def test_indicators_route(client):
    response = client.get('/api/indicators')
    assert response.status_code == 200
    data = response.json()
    assert 'indicators' in data or 'data' in data


def test_homepage_renders_status_badge(client):
    """The SSR homepage renders the app title."""
    response = client.get('/')
    assert response.status_code == 200
    html = response.text
    assert 'SimiVision' in html
