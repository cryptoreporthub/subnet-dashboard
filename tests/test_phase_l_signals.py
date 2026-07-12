"""Phase L — signals pipeline, alerts, persistence, and WebSocket."""

from __future__ import annotations

import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from internal.signals.alerts import AlertEngine
from internal.signals.pipeline import build_signal_for_subnet, generate_live_signals
from internal.signals.store import SignalStore
from server import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def temp_signal_store(tmp_path, monkeypatch):
    path = str(tmp_path / "signals.json")
    monkeypatch.setenv("SIGNALS_PATH", path)
    return SignalStore(path=path)


def test_signal_store_append_and_summary(temp_signal_store):
    store = temp_signal_store
    sig = {
        "subnet_id": 1,
        "signal_type": "buy",
        "confidence": 0.8,
        "source_expert": "quant",
        "timestamp": "2026-07-12T00:00:00Z",
        "evidence": "test",
    }
    store.append(sig)
    assert len(store.latest_all()) == 1
    summary = store.summary()["summary"]
    assert summary["buy_count"] == 1
    assert summary["avg_confidence"] == 0.8


def test_build_signal_for_subnet_shape():
    sn = {
        "netuid": 1,
        "name": "Test",
        "price": 10.0,
        "volume": 100000,
        "price_change_24h": 5.0,
        "emission": 2.0,
        "apy": 30.0,
    }
    row = build_signal_for_subnet(sn, {"tao_change_24h": 0.0, "weights": {}})
    assert row["subnet_id"] == 1
    assert row["signal_type"] in ("buy", "sell", "neutral")
    assert row["source_expert"] in ("quant", "hype", "dark_horse", "technical")
    assert 0.0 <= row["confidence"] <= 1.0
    assert row["evidence"]


def test_alert_engine_subscribe_and_recent(tmp_path, monkeypatch):
    alerts_path = str(tmp_path / "alerts.json")
    subs_path = str(tmp_path / "subs.json")
    monkeypatch.setenv("ALERTS_PATH", alerts_path)
    monkeypatch.setenv("ALERT_SUBSCRIPTIONS_PATH", subs_path)
    engine = AlertEngine(alerts_path=alerts_path, subscriptions_path=subs_path)
    result = engine.subscribe_webhook("https://example.com/hook")
    assert result["status"] == "success"
    engine._append_alert(
        {
            "alert_type": "weight_divergence",
            "message": "test",
            "dedupe_key": "weight_divergence",
        }
    )
    payload = engine.recent_alerts(limit=5)
    assert payload["status"] == "success"
    assert len(payload["alerts"]) == 1


def test_api_signals_and_summary(client):
    resp = client.get("/api/signals")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert isinstance(body["signals"], list)
    assert body["meta"]["count"] >= 100  # registry ~128 subnets

    summary = client.get("/api/signals/summary")
    assert summary.status_code == 200
    assert "summary" in summary.json()


def test_api_alerts_and_subscribe(client):
    alerts = client.get("/api/alerts")
    assert alerts.status_code == 200
    assert alerts.json()["status"] == "success"

    sub = client.post("/api/alerts/subscribe", json={"url": "https://example.com/alerts"})
    assert sub.status_code == 200
    assert sub.json()["status"] == "success"

    bad = client.post("/api/alerts/subscribe", json={"url": "ftp://bad"})
    assert bad.status_code == 200
    assert bad.json()["status"] == "error"


def test_ws_signals_connect(client):
    with client.websocket_connect("/ws/signals") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "connected"
        assert "signals" in msg["data"]
        ws.send_text("ping")
        pong = ws.receive_json()
        assert pong["type"] in ("pong", "signals")
