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
    assert any(k in weights for k in ('quant', 'hype', 'dark_horse', 'technical'))


def test_learning_stats_route(client):
    response = client.get('/api/learning/stats')
    assert response.status_code == 200
    data = response.json()
    payload = data.get('data', data)
    assert 'expert_weights' in payload
    assert 'last_updated' in payload
    assert any(k in payload['expert_weights'] for k in ('quant', 'hype', 'dark_horse', 'technical'))


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


def test_judges_api_routes(client):
    """Judges endpoints return 200 and structured data."""
    for path in ['/api/judges', '/api/portfolios', '/api/judges/oracle/postmortems',
                 '/api/subnets', '/api/indicators', '/api/simivision', '/api/top-pick/hour']:
        response = client.get(path)
        assert response.status_code == 200, f"{path} returned {response.status_code}"


def test_homepage_renders_with_malformed_judge_cards(client, monkeypatch):
    """The SSR homepage survives a malformed judge_cards value."""
    import server

    def _broken_build(*args, **kwargs):
        # Return a dict keyed by dicts to exercise the safe_list filter.
        # Python dicts cannot hold dict keys, so return a dict of dicts which
        # the template's safe_list filter will convert to values.
        return {
            "oracle": {"name": "Oracle", "role": "oracle", "score": 0.75,
                       "confidence": 0.82, "win_pct": 60.0, "pnl": 0.05,
                       "open_positions": 2, "postmortems": 1},
            "echo": {"name": "Echo", "role": "echo", "score": 0.65,
                     "confidence": 0.70, "win_pct": 55.0, "pnl": 0.03,
                     "open_positions": 1, "postmortems": 0},
        }

    monkeypatch.setattr(server, "_build_judge_cards", _broken_build)
    response = client.get('/')
    assert response.status_code == 200, response.text[:1000]
    assert 'Judge Panel' in response.text or 'Oracle' in response.text
