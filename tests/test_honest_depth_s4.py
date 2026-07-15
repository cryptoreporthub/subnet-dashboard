"""§17.S4 — honest whale/rugger/indicator payloads (one check per family)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from server import app


def _reset_whales_ruggers_singletons():
    import internal.ruggers.routes as ruggers_routes
    import internal.whales.routes as whales_routes

    whales_routes._service = None
    ruggers_routes._watchlist = None


@pytest.fixture
def client(tmp_path, monkeypatch):
    empty_intel = tmp_path / "whale_intel.json"
    empty_intel.write_text(
        json.dumps(
            {
                "updated_at": "2026-07-15T00:00:00+00:00",
                "events": [],
                "open_positions": {},
                "profiles": {},
                "closed_trades": [],
            }
        ),
        encoding="utf-8",
    )
    missing_indicators = tmp_path / "missing_indicator_state.json"
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text(
        json.dumps({"soul_map_state": {"learning_trail": [], "message_intel": {}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("WHALES_DATA_PATH", str(empty_intel))
    monkeypatch.setenv("WHALES_CONFIG_PATH", str(tmp_path / "whales.json"))
    (tmp_path / "whales.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("INDICATOR_STATE_PATH", str(missing_indicators))
    monkeypatch.setenv("SOUL_MAP_PATH", str(soul_path))
    _reset_whales_ruggers_singletons()
    with TestClient(app) as c:
        yield c


def test_api_whales_honest_empty(client):
    summary = client.get("/api/whales/summary").json()
    assert summary["status"] == "success"
    assert summary["data_available"] is False
    assert summary["reason"] == "no_events"
    assert summary["source"] == "ledger"
    assert summary["stats"]["total_events"] == 0

    flow = client.get("/api/whales/subnet/1/flow").json()
    assert flow["status"] == "success"
    assert flow["data_available"] is False
    assert "smart_money_present" not in flow
    assert "avoid_follow" not in flow


def test_api_ruggers_honest_empty_and_same_ledger(client):
    summary = client.get("/api/ruggers/summary").json()
    assert summary["status"] == "success"
    assert summary["data_available"] is False
    assert summary["reason"] == "no_events"
    assert summary["stats"]["total_events"] == 0

    risk = client.get("/api/ruggers/subnet/1").json()
    assert risk["status"] == "success"
    assert risk["data_available"] is False
    assert "avoid_follow" not in risk

    whales = client.get("/api/whales/summary").json()
    assert whales["stats"]["total_events"] == summary["stats"]["total_events"]


def test_api_indicators_honest_empty(client, monkeypatch):
    monkeypatch.setattr(
        "internal.indicators.routes._compute_technical_indicators",
        lambda sn: {"degraded": True, "history_source": "unavailable"},
    )
    body = client.get("/api/indicators").json()
    assert body["status"] == "success"
    assert body["data_available"] is False
    assert body["reason"] == "scheduler_never_ran"
    assert body["source"] == "none"

    conv = client.get("/api/indicators-convergence").json()
    assert conv["data_available"] is False
    assert conv["reason"] == "no_ohlcv"
    if conv["subnets"]:
        assert conv["subnets"][0]["degraded"] is True
        assert conv["subnets"][0]["oversold"]["reason"] == "no_ohlcv"
