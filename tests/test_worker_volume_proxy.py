"""Tests for split_v2 worker volume proxy."""

from __future__ import annotations

from unittest.mock import patch
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
    monkeypatch.setenv("DATA_DIR", "/nonexistent")
    from internal.data_volume import needs_worker_volume_proxy

    assert needs_worker_volume_proxy() is True


def test_needs_worker_volume_proxy_split_v2_web_with_local_data(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("DATA_DIR_IS_VOLUME", raising=False)
    (tmp_path / "soul_map.json").write_text("{}")
    from internal.data_volume import needs_worker_volume_proxy

    # Orphan JSON without a volume mount — still proxy to worker.
    assert needs_worker_volume_proxy() is True


def test_needs_worker_volume_proxy_false_when_volume_mounted(tmp_path, monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATA_DIR_IS_VOLUME", "1")
    (tmp_path / "soul_map.json").write_text("{}")
    from internal.data_volume import needs_worker_volume_proxy

    assert needs_worker_volume_proxy() is False


def test_should_proxy_learning_health(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("DATA_DIR", "/nonexistent")
    from internal.worker_proxy import should_proxy_path, should_proxy_write_path

    assert should_proxy_path("/api/learning/health") is True
    assert should_proxy_path("/api/learning/stats") is True
    assert should_proxy_path("/api/learning-metrics") is True
    assert should_proxy_path("/api/data-freshness") is True
    assert should_proxy_path("/api/dev-radar") is True
    assert should_proxy_path("/api/pump-alerts") is True
    assert should_proxy_path("/api/daily-pick") is True
    assert should_proxy_path("/api/pump-ladder/state") is True
    assert should_proxy_write_path("POST", "/api/pump-ladder/scan") is True
    assert should_proxy_write_path("GET", "/api/pump-ladder/scan") is False
    assert should_proxy_path("/api/predictions") is True
    assert should_proxy_path("/api/predictions/resolved") is True
    assert should_proxy_path("/api/mindmap/trail") is True
    assert should_proxy_path("/api/mindmap/graph") is True
    assert should_proxy_path("/api/council/weights") is True
    assert should_proxy_path("/api/council") is False


def test_learning_stats_proxy_middleware(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("DATA_DIR", "/nonexistent")

    from starlette.responses import JSONResponse

    async def _fake_proxy(_request):
        return JSONResponse(
            {
                "status": "success",
                "data": {"graded": 12, "accuracy": 0.5, "trust_banner": {"graded": 12}},
            }
        )

    with patch("internal.worker_proxy.proxy_get_to_worker", _fake_proxy):
        from server import app

        client = TestClient(app)
        r = client.get("/api/learning/stats")
    assert r.status_code == 200
    assert r.json()["data"]["graded"] == 12


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


def test_worker_internal_bases_ignores_flycast_secret_without_opt_in(monkeypatch):
    monkeypatch.setenv("FLY_APP_NAME", "subnet-dashboard")
    monkeypatch.setenv("WORKER_INTERNAL_URL", "http://subnet-dashboard.flycast:8080")
    monkeypatch.delenv("WORKER_INTERNAL_USE_FLYCAST", raising=False)
    from internal.worker_proxy import worker_internal_bases

    bases = worker_internal_bases()
    assert "http://subnet-dashboard.flycast:8080" not in bases
    assert "http://subnet-dashboard.flycast:8081" in bases
    assert "http://worker.process.subnet-dashboard.internal:8081" in bases


def test_worker_internal_bases_machine_ip_after_flycast(monkeypatch):
    monkeypatch.setenv("FLY_APP_NAME", "subnet-dashboard")
    monkeypatch.setenv(
        "WORKER_INTERNAL_URL",
        "http://[fdaa:80:e535:a7b:76d:4c6c:c6a8:2]:8081",
    )
    monkeypatch.delenv("WORKER_INTERNAL_USE_FLYCAST", raising=False)
    from internal.worker_proxy import worker_internal_bases

    bases = worker_internal_bases()
    flycast = "http://subnet-dashboard.flycast:8081"
    machine = "http://[fdaa:80:e535:a7b:76d:4c6c:c6a8:2]:8081"
    assert bases[0] == flycast
    assert machine in bases
    assert bases.index(flycast) < bases.index(machine)


def test_record_good_base_skips_machine_ip(monkeypatch):
    import internal.worker_proxy as wp

    monkeypatch.setattr(wp, "_LAST_GOOD_BASE", None)
    wp._record_good_base("http://[fdaa::1]:8081")
    assert wp._LAST_GOOD_BASE is None
    wp._record_good_base("http://subnet-dashboard.flycast:8081")
    assert wp._LAST_GOOD_BASE == "http://subnet-dashboard.flycast:8081"


def test_worker_internal_bases_includes_regional_dns(monkeypatch):
    monkeypatch.setenv("FLY_APP_NAME", "subnet-dashboard")
    monkeypatch.setenv("FLY_REGION", "sjc")
    monkeypatch.delenv("WORKER_INTERNAL_URL", raising=False)
    from internal.worker_proxy import worker_internal_bases

    bases = worker_internal_bases()
    assert "http://worker.process.sjc.subnet-dashboard.internal:8081" in bases


def test_load_weights_for_ui_proxies_worker(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("DATA_DIR", "/nonexistent")
    remote = {
        "expert_weights": {
            "quant": 1.2,
            "hype": 0.9,
            "dark_horse": 1.0,
            "technical": 0.8,
        }
    }
    with patch("internal.worker_proxy.fetch_learning_stats_sync", return_value=remote):
        from internal.council.weights import load_weights_for_ui

        weights = load_weights_for_ui()
    assert weights["quant"] == 1.2
    assert weights["technical"] == 0.8


def test_weights_are_default_flat():
    from internal.council.weights import DEFAULT_WEIGHTS, weights_are_default_flat

    assert weights_are_default_flat(dict(DEFAULT_WEIGHTS)) is True
    assert weights_are_default_flat({"quant": 1.1, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}) is False


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
