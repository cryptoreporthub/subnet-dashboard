from __future__ import annotations

from fastapi.testclient import TestClient

from internal.message_intel.entitlements import entitlement_from_request, entitlement_payload
from server import app


def test_entitlement_resolution_beta_bypass(monkeypatch):
    monkeypatch.setenv("TELEGRAM_LISTENER_BETA_BYPASS", "1")
    ent = entitlement_from_request()
    assert ent.is_pro_plus is True
    assert entitlement_payload(ent)["beta_bypass"] is True


def test_message_intel_free_reads_remain_available(monkeypatch, tmp_path):
    monkeypatch.delenv("TELEGRAM_LISTENER_BETA_BYPASS", raising=False)
    monkeypatch.setenv("MESSAGE_INTEL_DB", str(tmp_path / "message_intel.db"))
    from internal.message_intel import store

    store.reset_db_cache()
    with TestClient(app) as client:
        payload = client.get("/api/message-intel?limit=1").json()
    assert payload["status"] == "success"
    assert payload["meta"]["total_messages"] >= 0


def test_listener_surfaces_are_open_without_a_premium_gate(monkeypatch, tmp_path):
    monkeypatch.delenv("TELEGRAM_LISTENER_BETA_BYPASS", raising=False)
    monkeypatch.setenv("MESSAGE_INTEL_DB", str(tmp_path / "message_intel.db"))
    from internal.message_intel import store

    store.reset_db_cache()
    with TestClient(app) as client:
        resp = client.get("/api/message-intel/callers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] != "upgrade_required"
    assert "callers" in body


def test_trending_requested_limit_is_open_without_a_premium_gate(monkeypatch):
    monkeypatch.delenv("TELEGRAM_LISTENER_BETA_BYPASS", raising=False)
    monkeypatch.setattr(
        "internal.message_intel.rollup.build_trending_subnets",
        lambda **kw: [{"netuid": i, "name": f"SN{i}"} for i in range(kw["limit"])],
    )
    with TestClient(app) as client:
        free = client.get("/api/message-intel/trending-v2?limit=50").json()
    assert len(free["items"]) == 50
