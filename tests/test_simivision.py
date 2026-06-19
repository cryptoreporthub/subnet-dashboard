import json
import pytest
from server import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
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
