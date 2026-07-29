"""Tests for pump desk payload resolution on split_v2 web."""

from __future__ import annotations

from unittest.mock import patch


def test_load_pump_alerts_desk_payload_proxies_to_worker(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("DATA_DIR", "/nonexistent")
    remote = {
        "status": "success",
        "count": 1,
        "early_count": 1,
        "confirmed_count": 0,
        "alerts": [{"timing": "lead", "netuid": 12}],
        "desk": True,
    }
    with patch("internal.worker_proxy.fetch_worker_json_sync", return_value=remote):
        from internal.pump.desk_payload import load_pump_alerts_desk_payload

        out = load_pump_alerts_desk_payload([])
    assert out["count"] == 1
    assert out["alerts"][0]["netuid"] == 12


def test_load_pump_alerts_desk_payload_falls_back_local(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("DATA_DIR", "/nonexistent")
    local = {"status": "empty", "count": 0, "alerts": [], "desk": True}
    with patch("internal.worker_proxy.fetch_worker_json_sync", side_effect=OSError("down")):
        with patch(
            "internal.learning.pump_alert.build_pump_alerts_desk",
            return_value=local,
        ):
            from internal.pump.desk_payload import load_pump_alerts_desk_payload

            out = load_pump_alerts_desk_payload([])
    assert out["status"] == "empty"
    assert out["count"] == 0
