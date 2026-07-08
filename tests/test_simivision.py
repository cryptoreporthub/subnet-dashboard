"""Tests for the live SimiVision engine and server endpoints."""

import pytest
from fastapi.testclient import TestClient

from internal.simivision.engine import SimiVisionEngine
from server import app, _app_version


@pytest.fixture
def client():
    return TestClient(app)


def test_api_simivision_shape(client):
    """/api/simivision returns a success payload with top signals and meta."""
    response = client.get("/api/simivision")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "data" in data
    snapshot = data["data"]
    assert "top" in snapshot
    assert "meta" in snapshot
    assert isinstance(snapshot["top"], list)
    for signal in snapshot["top"]:
        assert "netuid" in signal
        assert "name" in signal
        assert "conviction" in signal
        assert "recommendation" in signal


def test_api_simivision_canonical_names(client):
    """Signal names should match the registry."""
    response = client.get("/api/simivision")
    assert response.status_code == 200
    data = response.json()
    top = data["data"]["top"]
    registry_response = client.get("/api/subnets")
    assert registry_response.status_code == 200
    registry = registry_response.json()
    subnets = {sn.get("netuid"): sn for sn in registry.get("subnets", [])}
    for signal in top:
        netuid = signal["netuid"]
        canonical = subnets.get(netuid, {}).get("name")
        assert canonical is not None, f"netuid {netuid} missing from registry"
        assert signal["name"] == canonical


def test_homepage_renders_simivision(client):
    """The SSR homepage renders the SimiVision title."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "SimiVision" in html


def test_simivision_engine_top_signals():
    """The engine returns ranked signals with required fields."""
    engine = SimiVisionEngine()
    signals = engine.top_signals(n=3)
    assert isinstance(signals, list)
    assert len(signals) <= 3
    for signal in signals:
        assert "netuid" in signal
        assert "name" in signal
        assert "conviction" in signal
        assert "recommendation" in signal


def test_simivision_engine_get_signal():
    """The engine can fetch a signal by netuid."""
    engine = SimiVisionEngine()
    signals = engine.top_signals(n=1)
    if not signals:
        pytest.skip("No signals available")
    netuid = signals[0]["netuid"]
    signal = engine.get_signal(netuid)
    assert signal is not None
    assert signal["netuid"] == netuid


def test_simivision_engine_safe_snapshot():
    """The safe snapshot exposes top signals and metadata."""
    engine = SimiVisionEngine()
    snapshot = engine.safe_snapshot(n=2)
    assert "top" in snapshot
    assert "meta" in snapshot
    assert isinstance(snapshot["top"], list)
    assert len(snapshot["top"]) <= 2


def test_app_version_export():
    """_app_version is exposed and returns a semver string."""
    version = _app_version()
    assert isinstance(version, str)
    parts = version.split(".")
    assert len(parts) >= 2
    assert all(p.isdigit() for p in parts[:2])
