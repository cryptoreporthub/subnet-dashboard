"""§33 — production readiness probe."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from server import app

client = TestClient(app)


def test_worker_data_freshness_proxies(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("DATA_DIR", "/nonexistent")
    remote = {
        "source": "blockmachine",
        "subnet_count": 128,
        "stale": False,
        "last_sync": "2026-07-29T00:00:00+00:00",
        "effective_source": "blockmachine",
        "effective_total": 128,
        "registry_count": 128,
        "tmc_cache_count": 129,
    }
    with patch("internal.worker_proxy.fetch_worker_json_sync", return_value=remote):
        from internal.data_volume import worker_data_freshness

        out = worker_data_freshness()
    assert out["subnet_count"] == 128
    assert out["effective_source"] == "blockmachine"


def test_live_data_freshness_uses_worker_on_split_v2_web(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("DATA_DIR", "/nonexistent")
    remote = {
        "source": "blockmachine",
        "subnet_count": 120,
        "stale": False,
        "effective_source": "blockmachine",
        "effective_total": 120,
    }
    with patch("internal.worker_proxy.fetch_worker_json_sync", return_value=remote):
        from internal.live_subnets import live_data_freshness

        info = live_data_freshness()
    assert info["subnet_count"] == 120
    assert info["stale"] is False


def test_probe_feed_layers_uses_worker_on_split_v2_web(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("DATA_DIR", "/nonexistent")
    remote = {
        "subnet_count": 120,
        "stale": False,
        "last_sync": "2026-07-29T00:00:00+00:00",
        "effective_source": "blockmachine",
        "effective_total": 120,
        "registry_count": 128,
        "tmc_cache_count": 129,
    }
    with patch("internal.worker_proxy.fetch_worker_json_sync", return_value=remote):
        from internal.subnets.feed import probe_feed_layers

        feed = probe_feed_layers()
    assert feed["effective_source"] == "blockmachine"
    assert feed["live_cache"]["count"] == 120
    assert feed["likely_total"] == 120


def test_readiness_skips_live_cache_empty_when_feed_ok(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("DATA_DIR", "/nonexistent")
    remote = {
        "source": "blockmachine",
        "subnet_count": 0,
        "stale": True,
        "effective_source": "taomarketcap",
        "effective_total": 129,
        "registry_count": 128,
        "tmc_cache_count": 129,
    }
    with patch("internal.worker_proxy.fetch_worker_json_sync", return_value=remote):
        from internal.ops.readiness import build_readiness_report

        report = build_readiness_report()
    assert "live_subnets_cache_empty" not in report["issues"]
    assert report["subnet_feed"]["effective_source"] == "taomarketcap"


def test_readiness_proxies_learning_loop_health(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("DATA_DIR", "/nonexistent")
    remote = {
        "status": "ok",
        "last_resolver_tick": "2026-07-28T12:00:00+00:00",
        "ledger": {"gap": False},
    }
    with patch("internal.worker_proxy.fetch_worker_json_sync", return_value=remote):
        from internal.ops.readiness import build_readiness_report

        report = build_readiness_report()
    assert report["learning_loop_health"]["last_resolver_tick"] == "2026-07-28T12:00:00+00:00"
    assert report["learning_loop_health"]["status"] == "ok"


def test_readiness_split_v2_web_shows_worker_resolver_running(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("WORKER_SPLIT_V2", "on")
    monkeypatch.setenv("DATA_DIR", "/nonexistent")
    remote_health = {
        "status": "ok",
        "last_resolver_tick": "2026-07-29T12:00:00+00:00",
        "resolver": {"running": True, "last_ok": True, "peer": "dedicated_worker"},
        "ledger": {"gap": False},
    }
    with patch("internal.worker_proxy.fetch_worker_json_sync", return_value=remote_health):
        with patch(
            "internal.worker_peer.get_worker_peer",
            return_value={"expected": True, "alive": True, "peer": "dedicated_worker"},
        ):
            with patch(
                "internal.council.resolver_scheduler.get_prediction_resolver_scheduler_state",
                return_value={"running": False, "refresh_minutes": 15},
            ):
                from internal.ops.readiness import build_readiness_report

                report = build_readiness_report()
    assert report["resolver"]["running"] is True
    assert report["resolver"]["peer"] == "dedicated_worker"
    assert "prediction_resolver_not_running" not in report["issues"]


def test_ops_readiness_contract():
    resp = client.get("/api/ops/readiness")
    assert resp.status_code == 200
    body = resp.json()
    assert "ready" in body
    assert "issues" in body
    assert "learning" in body
    assert "resolver" in body
    assert "subnet_feed" in body
    assert "daily_pick" in body
    assert "next_levers" in body
    assert body.get("worker_mode") in ("web", "worker", "combined", "split", "split_v2")


def test_data_freshness_effective_fields():
    resp = client.get("/api/data-freshness")
    assert resp.status_code == 200
    body = resp.json()
    assert "effective_source" in body
    assert "effective_total" in body
