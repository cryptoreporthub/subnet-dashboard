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


REQUIRED_SIGNAL_FIELDS = {
    "netuid",
    "name",
    "rank",
    "conviction",
    "rationale",
    "reason_tag",
    "delta",
    "delta_value",
    "freshness",
    "freshness_human",
    "source",
    "status",
}

REQUIRED_META_FIELDS = {
    "source",
    "freshness",
    "freshness_human",
    "provenance_log",
    "system_status",
    "total_signals",
    "selector_decisions",
    "fallback_used",
    "error",
    "council_weights",
    "expert_track_records",
}


def test_api_simivision_shape(client):
    response = client.get("/api/simivision")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "success"
    assert "data" in data
    assert "freshness" in data

    snapshot = data["data"]
    assert "top" in snapshot
    assert "meta" in snapshot
    assert "date" in snapshot

    meta = snapshot["meta"]
    assert REQUIRED_META_FIELDS.issubset(meta.keys())
    assert isinstance(meta["provenance_log"], list)
    assert meta["system_status"] in {"Operative", "Dimmed", "Hibernating", "Error"}

    assert set(meta["council_weights"].keys()) >= {"quant", "hype", "contrarian"}
    assert all(0.0 <= w <= 1.0 for w in meta["council_weights"].values())
    assert isinstance(meta["expert_track_records"], dict)

    top = snapshot["top"]
    assert isinstance(top, list)
    assert 0 <= len(top) <= 3

    for signal in top:
        assert REQUIRED_SIGNAL_FIELDS.issubset(signal.keys())
        assert isinstance(signal["netuid"], int)
        assert isinstance(signal["name"], str)
        assert signal["name"] != "Unknown"
        assert isinstance(signal["rank"], int)
        assert isinstance(signal["conviction"], (int, float))
        assert 0 <= signal["conviction"] <= 100
        assert isinstance(signal["rationale"], str)
        assert isinstance(signal["reason_tag"], str)
        assert signal["delta"] in {"+", "-", "stable"}
        assert isinstance(signal["delta_value"], (int, float))
        assert isinstance(signal["freshness"], str)
        assert isinstance(signal["freshness_human"], str)
        assert isinstance(signal["source"], str)
        assert signal["status"] in {"Operative", "Dimmed", "Hibernating", "Error"}


def test_api_simivision_canonical_names(client):
    """Canonical subnet names must come from registry.json, not be ad-hoc transformed."""
    response = client.get("/api/simivision")
    assert response.status_code == 200
    data = json.loads(response.data)
    top = data["data"]["top"]

    registry_response = client.get("/api/registry")
    registry = json.loads(registry_response.data)

    for signal in top:
        netuid = signal["netuid"]
        canonical = registry.get(str(netuid), {}).get("name")
        assert canonical is not None, f"netuid {netuid} missing from registry"
        assert signal["name"] == canonical, (
            f"netuid {netuid} name mismatch: {signal['name']} != {canonical}"
        )


def test_homepage_renders_spine(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.data.decode()
    assert 'id="simivision-spine"' in html
    assert "simivision-hero-card" in html
    assert "hero-conviction-ring" in html
    assert "simivision-provenance" in html


def test_api_simivision_does_not_break_existing_signals(client):
    """The new endpoint should coexist with existing Signals API endpoints."""
    response = client.get("/api/summary")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "success"
    assert "summary" in data


REQUIRED_TRACE_FIELDS = {
    "expert_breakdown",
    "brain",
    "judge_verdict",
    "economics",
    "rationale",
    "invalidation",
    "horizon",
    "preferred_entry",
}


def test_api_simivision_trace_shape(client):
    """The trace endpoint returns the expected envelope and nested fields."""
    response = client.get("/api/simivision/1/trace")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["status"] == "success"
    assert data["netuid"] == 1
    assert isinstance(data["name"], str)
    assert data["name"] != "Unknown"
    assert "signal" in data
    assert "trace" in data

    signal = data["signal"]
    assert signal["netuid"] == 1
    assert isinstance(signal["name"], str)

    trace = data["trace"]
    assert REQUIRED_TRACE_FIELDS.issubset(trace.keys())

    assert set(trace["expert_breakdown"].keys()) >= {"quant", "hype", "contrarian"}
    for expert in trace["expert_breakdown"].values():
        assert "score" in expert

    assert "action" in trace["brain"]
    assert "target_weight" in trace["brain"]
    assert "agreement" in trace["brain"]

    assert "score" in trace["judge_verdict"]
    assert "action" in trace["judge_verdict"]
    assert "note" in trace["judge_verdict"]

    econ = trace["economics"]
    for key in ("emission", "social_mentions", "apy", "total_stake", "is_overvalued", "risk_flags"):
        assert key in econ
    assert isinstance(econ["risk_flags"], list)

    assert isinstance(trace["rationale"], str)
    assert isinstance(trace["invalidation"], str)
    assert isinstance(trace["horizon"], str)
    assert isinstance(trace["preferred_entry"], str)


def test_api_simivision_trace_for_known_subnet(client):
    """A subnet returned from /api/simivision should have a working trace endpoint."""
    response = client.get("/api/simivision")
    assert response.status_code == 200
    data = json.loads(response.data)
    top = data["data"]["top"]
    assert top, "No SimiVision signals returned to test trace endpoint"

    for signal in top:
        netuid = signal["netuid"]
        trace_response = client.get(f"/api/simivision/{netuid}/trace")
        assert trace_response.status_code == 200, f"Trace failed for netuid {netuid}"
        trace_data = json.loads(trace_response.data)
        assert trace_data["status"] == "success"
        assert trace_data["netuid"] == netuid
        assert trace_data["name"] == signal["name"]


def test_api_simivision_trace_missing_subnet(client):
    """Unknown netuids should return a graceful error without a 500."""
    response = client.get("/api/simivision/99999/trace")
    assert response.status_code in (404, 503)
    data = json.loads(response.data)
    assert data["status"] == "error"
    assert "netuid" in data

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
         patch('server.MindmapBridge') as mock_bridge_cls:
        mock_load.return_value = {}
        mock_bridge_cls.return_value.get_brain_recommendations.return_value = {'recommendations': {}}
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