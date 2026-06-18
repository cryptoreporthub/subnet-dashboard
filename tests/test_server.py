import pytest
import json
from server import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_index_route(client):
    response = client.get('/')
    assert response.status_code == 200
    html = response.data.decode()
    assert 'Protocol watchlist' in html
    assert 'HYPE' in html
    assert 'Hyperliquid' in html

def test_registry_route(client):
    response = client.get('/api/registry')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert isinstance(data, dict)

def test_subnet_route_found(client):
    # Subnet 1 should exist in config/registry.json
    response = client.get('/api/subnet/1')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['subnet_id'] == 1
    assert 'data' in data

def test_subnet_route_not_found(client):
    # Subnet 999999 should not exist
    response = client.get('/api/subnet/999999')
    assert response.status_code == 404
    data = json.loads(response.data)
    assert 'error' in data

def test_health_route(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert response.data == b"OK"

def test_cors_headers(client):
    response = client.get('/api/registry')
    assert response.headers.get('Access-Control-Allow-Origin') == '*'
    assert response.headers.get('X-Frame-Options') == 'ALLOWALL'


def test_stats_route(client):
    response = client.get('/api/stats')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'success'
    assert 'summary' in data
    summary = data['summary']
    assert 'total_subnets' in summary
    assert 'status_counts' in summary
    assert 'total_stake' in summary
    assert 'total_emission' in summary
    assert 'total_social_mentions' in summary
    assert 'overvalued_count' in summary
    assert 'avg_apy' in summary
    assert 'top_emitters' in data
    assert 'top_staked' in data
    assert 'top_mentioned' in data
    assert 'flagged_subnets' in data


def test_stats_route_headers(client):
    response = client.get('/api/stats')
    assert response.status_code == 200
    assert response.headers.get('Access-Control-Allow-Origin') == '*'
    assert response.headers.get('X-Frame-Options') == 'ALLOWALL'
    assert response.headers.get('Cache-Control') == 'public, max-age=30'


def test_subnets_list_route(client):
    response = client.get('/api/subnets?status=active&sort=emission&order=desc&limit=2')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'success'
    assert 'meta' in data
    assert 'subnets' in data
    assert len(data['subnets']) <= 2


def test_recommendations_route(client):
    response = client.get('/api/recommendations')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'success'
    assert 'recommendations' in data['data']


def test_soul_map_route(client):
    response = client.get('/api/soul-map')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'success'
    assert 'data' in data


def test_daily_rotation_route(client):
    response = client.get('/api/daily-rotation')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'success'
    assert 'data' in data
    assert 'decisions' in data['data']
    assert 'recommendations' in data['data']


def test_watchlist_route(client):
    response = client.get('/api/watchlist')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'success'
    assert 'data' in data
    protocols = data['data']['protocols']
    symbols = {p['symbol'] for p in protocols}
    assert symbols >= {'VVV', 'FET', 'RENDER', 'TAO', 'HYPE'}
    assert any(p['symbol'] == 'HYPE' and p['name'] == 'Hyperliquid' for p in protocols)
    assert data['freshness']['threshold_seconds'] == 300
