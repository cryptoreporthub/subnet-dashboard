"""Phase L slices 2–4 — alerts, WebSocket, rules engine."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from internal.signals.alerts import AlertEngine
from internal.signals.pipeline import build_signal, generate_signals
from internal.signals.rules import (
    apply_hot_sell_precedence,
    derive_signal_type,
    dominant_label,
    should_skip_alert,
    validate_alert_payload,
)
from internal.signals.store import SignalStore
from internal.signals.ws_hub import SignalBroadcastHub
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


@pytest.fixture
def temp_alerts(tmp_path, monkeypatch):
    alerts_path = str(tmp_path / "alerts.json")
    subs_path = str(tmp_path / "subs.json")
    monkeypatch.setenv("ALERTS_PATH", alerts_path)
    monkeypatch.setenv("ALERT_SUBSCRIPTIONS_PATH", subs_path)
    return AlertEngine(alerts_path=alerts_path, subscriptions_path=subs_path)


def test_rules_sell_precedence_over_hot():
    hot = {"active": True, "reasons": ["momentum"]}
    sell = {"active": True, "reasons": ["overbought"]}
    hot_adj, sell_adj = apply_hot_sell_precedence(hot, sell)
    assert sell_adj.get("active") is True
    assert hot_adj.get("active") is False
    assert hot_adj.get("suppressed_by") == "SELL ALERT"
    assert derive_signal_type(75.0, hot, sell) == "sell"
    assert dominant_label(hot, sell) == "SELL ALERT"


def test_rules_hot_when_sell_inactive():
    hot = {"active": True}
    sell = {"active": False}
    assert derive_signal_type(55.0, hot, sell) == "buy"
    assert dominant_label(hot, sell) == "HOT"


def test_rules_alert_dedupe():
    existing = {"alert_type": "manual", "dedupe_key": "x", "active": True}
    candidate = {"alert_type": "manual", "dedupe_key": "x", "active": True}
    assert should_skip_alert(existing, candidate) is True
    assert validate_alert_payload({"alert_type": "", "message": "hi"}) is not None


def test_store_append_dedupes_unchanged(temp_signal_store):
    store = temp_signal_store
    row = {
        "subnet_id": 3,
        "signal_type": "buy",
        "confidence": 0.7,
        "source_expert": "hype",
        "timestamp": "2026-07-12T10:00:00Z",
        "evidence": "test",
    }
    assert len(store.append_many([row])) == 1
    assert len(store.append_many([row])) == 0


def test_alert_engine_create_and_preserve(temp_alerts):
    engine = temp_alerts
    first = engine.create_alert(
        {"alert_type": "manual", "message": "test alert", "severity": "info"}
    )
    assert first["status"] == "success"
    engine.create_alert(
        {"alert_type": "manual", "message": "second", "dedupe_key": "other"}
    )
    payload = engine.recent_alerts(limit=10)
    assert len(payload["alerts"]) == 2


def test_alert_post_rejects_malformed(client):
    bad = client.post("/api/alerts", json={"alert_type": "", "message": ""})
    assert bad.status_code == 200
    assert bad.json()["status"] == "error"


def test_api_alerts_get_and_post(client, tmp_path, monkeypatch):
    alerts_path = str(tmp_path / "alerts.json")
    subs_path = str(tmp_path / "subs.json")
    monkeypatch.setenv("ALERTS_PATH", alerts_path)
    monkeypatch.setenv("ALERT_SUBSCRIPTIONS_PATH", subs_path)
    import internal.signals.routes as routes

    routes._alerts = None
    get_resp = client.get("/api/alerts?refresh_checks=false")
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "success"

    post_resp = client.post(
        "/api/alerts",
        json={
            "alert_type": "manual",
            "message": "contract test",
            "severity": "warning",
            "subnet_id": 1,
        },
    )
    assert post_resp.status_code == 200
    body = post_resp.json()
    assert body["status"] == "success"
    assert body["alert"]["message"] == "contract test"


def test_api_signals_unchanged(client):
    resp = client.get("/api/signals?refresh=false")
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


def test_ws_signals_lifecycle(client):
    with client.websocket_connect("/ws/signals") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "connected"
        assert "signals" in msg["data"]
        ws.send_text("ping")
        pong = ws.receive_json()
        assert pong["type"] in ("pong", "signals")
        ws.send_text("refresh")
        types = set()
        for _ in range(3):
            refresh_msg = ws.receive_json()
            types.add(refresh_msg["type"])
            if "signals" in types:
                break
        assert "signals" in types


def test_ws_hub_broadcast_prunes_dead_clients():
    import asyncio

    hub = SignalBroadcastHub()

    class DeadSocket:
        async def send_text(self, _msg):
            raise ConnectionError("gone")

    class LiveSocket:
        def __init__(self):
            self.messages = []

        async def send_text(self, msg):
            self.messages.append(msg)

    async def run():
        dead = DeadSocket()
        live = LiveSocket()
        hub._clients = {dead, live}  # type: ignore[arg-type]
        await hub.broadcast("test", {"ok": True})
        assert hub.client_count == 1
        assert live.messages

    asyncio.run(run())


def test_build_signal_shape():
    sn = {
        "netuid": 1,
        "name": "Alpha",
        "price": 12.0,
        "volume": 50000,
        "price_change_24h": 3.0,
        "emission": 2.0,
        "apy": 25.0,
    }
    row = build_signal(sn, {"tao_change_24h": 0.0, "weights": {}})
    assert row["signal_type"] in ("buy", "sell", "neutral")
    assert row["source_expert"] in ("quant", "hype", "dark_horse", "technical")


def test_generate_signals_returns_changed_list():
    result = generate_signals(persist=False)
    assert result["status"] == "success"
    assert isinstance(result["signals"], list)
    assert "changed_signals" in result
