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