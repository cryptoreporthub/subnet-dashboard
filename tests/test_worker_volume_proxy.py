"""Tests for split_v2 worker volume proxy."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


def test_has_local_volume_data_with_soul_map(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from internal.data_volume import has_local_volume_data

    assert has_local_volume_data() is False
    (tmp_path / "soul_map.json").write_text("{}")
    assert has_local_volume_data() is True


def test_needs_worker_volume_proxy_split_v2_web(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    from internal.data_volume import needs_worker_volume_proxy

    assert needs_worker_volume_proxy() is True


def test_listener_status_proxies_to_worker(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("DATA_DIR", "/nonexistent")
    remote = {
        "listener": {
            "enabled": True,
            "live": True,
            "running": True,
            "reason": "running",
        }
    }
    with patch("internal.worker_proxy.fetch_worker_json_sync", return_value=remote):
        from internal.message_intel.listener_service import listener_status

        status = listener_status()
    assert status["live"] is True
    assert status["reason"] == "running"


def test_worker_proxy_middleware(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("DATA_DIR", "/nonexistent")

    from starlette.responses import JSONResponse

    async def _fake_proxy(_request):
        return JSONResponse({"status": "success", "count": 1})

    with patch("internal.worker_proxy.proxy_get_to_worker", _fake_proxy):
        from server import app

        client = TestClient(app)
        r = client.get("/api/pump-alerts")
    assert r.status_code == 200
    assert r.json().get("count") == 1
