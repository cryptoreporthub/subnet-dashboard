import json
import pytest
from unittest.mock import patch, MagicMock

from server import (
    app,
    _build_simivision_choices,
    _empty_simivision,
)


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def sample_registry():
    return {
        "1": {"id": 1, "name": "Subnet One", "status": "active", "emission": 10.0},
        "2": {"id": 2, "name": "Subnet Two", "status": "active", "emission": 9.0},
        "3": {"id": 3, "name": "Subnet Three", "status": "active", "emission": 8.0},
    }


@pytest.fixture
def sample_recommendations():
    return {
        "recommendations": {
            "2": {
                "target_weight": 0.35,
                "expected_return": 0.12,
                "volatility": 0.08,
                "conviction": 0.7,
                "rationale": "strong fundamentals",
            },
            "3": {
                "target_weight": 0.25,
                "expected_return": 0.08,
                "volatility": 0.05,
                "conviction": 0.6,
                "rationale": "steady momentum",
            },
        }
    }


def _choice_ids(payload):
    return [c['subnet_id'] for c in payload['choices']]


def test_api_simivision_includes_meta(client):
    """/api/simivision must expose provenance metadata alongside choices."""
    response = client.get('/api/simivision')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'success'
    assert 'data' in data
    simivision = data['data']
    assert 'choices' in simivision
    assert 'meta' in simivision
    meta = simivision['meta']
    assert 'source' in meta
    assert 'fallback_used' in meta
    assert 'selector_decisions' in meta
    assert 'brain_recommendations' in meta
    assert 'error' in meta


def test_api_simivision_empty_state(client):
    """When no live picks exist, /api/simivision returns a transparent empty payload."""
    with patch('server.load_data') as mock_load, \
         patch('server.bridge') as mock_bridge:
        mock_load.return_value = {}
        mock_bridge.get_brain_recommendations.return_value = {'recommendations': {}}
        response = client.get('/api/simivision')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['status'] == 'success'
    simivision = data['data']
    assert simivision['choices'] == []
    assert simivision['meta']['source'] == 'empty'
    assert simivision['meta']['fallback_used'] is False


def test_build_simivision_choices_backfills_with_brain(sample_registry, sample_recommendations):
    """When selector decisions are sparse, Brain recommendations back-fill to 3 cards."""
    decisions = [
        {
            'subnet_id': 1,
            'action': 'accumulate',
            'confidence': 0.8,
            'expert_breakdown': {
                'quant': {'score': 0.7, 'summary': 'q'},
                'hype': {'score': 0.6, 'summary': 'h'},
                'contrarian': {'score': 0.5, 'summary': 'c'},
            },
        }
    ]
    payload = _build_simivision_choices(
        sample_registry,
        decisions,
        sample_recommendations,
        feedback=None,
        bridge=None,
    )
    assert len(payload['choices']) == 3
    assert payload['meta']['source'] == 'selector+brain'
    assert payload['meta']['fallback_used'] is True
    assert payload['meta']['selector_decisions'] == 1
    assert payload['meta']['brain_recommendations'] == 2
    assert _choice_ids(payload) == [1, 2, 3]


def test_build_simivision_choices_selector_only(sample_registry, sample_recommendations):
    """When 3 selector decisions exist, no fallback is used."""
    decisions = [
        {
            'subnet_id': sid,
            'action': 'hold',
            'confidence': 0.7,
            'expert_breakdown': {
                'quant': {'score': 0.6, 'summary': 'q'},
                'hype': {'score': 0.6, 'summary': 'h'},
                'contrarian': {'score': 0.6, 'summary': 'c'},
            },
        }
        for sid in [1, 2, 3]
    ]
    payload = _build_simivision_choices(
        sample_registry,
        decisions,
        sample_recommendations,
        feedback=None,
        bridge=None,
    )
    assert len(payload['choices']) == 3
    assert payload['meta']['source'] == 'selector'
    assert payload['meta']['fallback_used'] is False
    assert payload['meta']['selector_decisions'] == 3
    assert payload['meta']['brain_recommendations'] == 0


def test_build_simivision_choices_registry_fallback(sample_registry):
    """With no selector decisions and no recommendations, registry highlights fill the gap."""
    payload = _build_simivision_choices(
        sample_registry,
        decisions=[],
        recommendations={'recommendations': {}},
        feedback=None,
        bridge=None,
    )
    assert len(payload['choices']) == 3
    assert payload['meta']['source'] == 'registry'
    assert payload['meta']['fallback_used'] is True


def test_empty_simivision_payload():
    """The helper produces a consistent transparent pending/error payload."""
    payload = _empty_simivision(error='boom')
    assert payload['choices'] == []
    assert payload['meta']['source'] == 'error'
    assert payload['meta']['fallback_used'] is False
    assert payload['meta']['error'] == 'boom'


def test_index_renders_simivision_meta(client):
    """The SSR homepage should render SimiVision provenance and pending container."""
    response = client.get('/')
    assert response.status_code == 200
    html = response.data.decode()
    assert 'simivision-meta-bar' in html
    assert 'simivision-source' in html
    assert 'simivision-empty' in html
    assert 'No live signals today' in html


def test_feedback_boost_flows_into_edge_score(sample_registry):
    """Full loop: POST feedback → _build_simivision_choices → edge_score reflects boost."""
    from internal.council.mindmap_bridge import MindmapBridge

    bridge = MindmapBridge()
    bridge._save_to_disk = MagicMock()  # prevent disk writes

    # Log positive feedback for subnet 1
    bridge.log_simivision_feedback(1, outcome=1, note="good pick")

    decisions = [
        {
            "subnet_id": 1,
            "recommended_action": "accumulate",
            "consensus_score": 0.7,
            "expert_breakdown": {
                "quant": {"score": 0.7, "summary": "q"},
                "hype": {"score": 0.6, "summary": "h"},
                "contrarian": {"score": 0.5, "summary": "c"},
            },
        }
    ]

    # With bridge (boost active)
    payload_with = _build_simivision_choices(
        sample_registry,
        decisions,
        {"recommendations": {}},
        feedback=None,
        bridge=bridge,
    )
    # Without bridge (no boost)
    payload_without = _build_simivision_choices(
        sample_registry,
        decisions,
        {"recommendations": {}},
        feedback=None,
        bridge=None,
    )

    edge_with = payload_with["choices"][0]["edge_score"]
    edge_without = payload_without["choices"][0]["edge_score"]
    boost = payload_with["choices"][0]["feedback_boost"]

    # boost = 1 * 0.02 = 0.02
    assert boost == 0.02
    # edge_score = (0.7 + boost) * 0.5 * 1.0 = 0.36 vs (0.7) * 0.5 * 1.0 = 0.35
    assert edge_with > edge_without
    assert edge_with == round((0.7 + 0.02) * 0.5 * 1.0, 4)
