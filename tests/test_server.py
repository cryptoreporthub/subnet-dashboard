import json

import pytest
from fastapi.testclient import TestClient

from server import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_index_route(client):
    response = client.get('/')
    assert response.status_code == 200


def test_registry_route(client):
    response = client.get('/api/registry')
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    if data:
        first = next(iter(data.values()))
        assert first.get('id') == first.get('netuid')


def test_subnet_route_found(client):
    # Subnet 1 should exist in config/registry.json
    response = client.get('/api/subnet/1')
    assert response.status_code == 200
    data = response.json()
    assert data['subnet_id'] == 1
    assert 'data' in data


def test_subnet_route_not_found(client):
    # Subnet 999999 should not exist
    response = client.get('/api/subnet/999999')
    assert response.status_code == 404
    data = response.json()
    assert 'error' in data


def test_health_route(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert response.text == "OK"


def test_cors_headers(client):
    response = client.get('/api/registry')
    assert response.headers.get('X-Frame-Options') == 'SAMEORIGIN'
    assert response.headers.get('Access-Control-Allow-Origin') is None


def test_cors_headers_allowed_origin(client):
    response = client.get(
        '/api/registry',
        headers={'Origin': 'https://subnet-dashboard.fly.dev'},
    )
    assert response.headers.get('X-Frame-Options') == 'SAMEORIGIN'
    assert response.headers.get('Access-Control-Allow-Origin') == 'https://subnet-dashboard.fly.dev'
    assert 'Origin' in (response.headers.get('Vary') or '')


def test_cors_headers_disallowed_origin(client):
    response = client.get(
        '/api/registry',
        headers={'Origin': 'https://evil.example'},
    )
    assert response.headers.get('Access-Control-Allow-Origin') is None


def test_stats_route(client):
    response = client.get('/api/stats')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'success'
    assert 'summary' in data
    assert 'top_emitters' in data
    assert 'flagged_subnets' in data


def test_subnets_list_route(client):
    response = client.get('/api/subnets?status=active&sort=emission&order=desc&limit=2')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'success'
    assert 'meta' in data
    assert 'subnets' in data
    assert len(data['subnets']) <= 2


def test_recommendations_route(client):
    response = client.get('/api/recommendations')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'success'
    assert 'recommendations' in data['data']


def test_soul_map_route(client):
    response = client.get('/api/soul-map')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'success'
    assert 'data' in data


def test_daily_rotation_route(client):
    response = client.get('/api/daily-rotation')
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'success'
    assert 'data' in data
    assert 'decisions' in data['data']
    assert 'recommendations' in data['data']
