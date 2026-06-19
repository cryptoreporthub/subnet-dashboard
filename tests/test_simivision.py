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
