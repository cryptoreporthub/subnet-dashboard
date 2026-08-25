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


def _patch_healthy_readiness_dependencies(monkeypatch, *, resolver_running=True, graded=1):
    monkeypatch.setattr(
        "internal.live_subnets.live_data_freshness",
        lambda: {"stale": False, "subnet_count": 96},
    )
    monkeypatch.setattr(
        "internal.subnets.feed.probe_feed_layers",
        lambda: {"likely_total": 96, "effective_source": "blockmachine"},
    )
    monkeypatch.setattr(
        "internal.freshness.get_sync_state",
        lambda: {"background_running": True, "last_sync_at": "2026-08-25T00:00:00Z", "last_sync_ok": True},
    )
    monkeypatch.setattr(
        "internal.council.resolver_scheduler.get_prediction_resolver_scheduler_state",
        lambda: {"running": resolver_running},
    )
    monkeypatch.setattr(
        "internal.ops.readiness._learning_summary",
        lambda: {"graded": graded, "pending": 0, "accuracy": None, "trust_ready": None},
    )
    monkeypatch.setattr("internal.ops.readiness._daily_pick_summary", lambda: {})
    monkeypatch.setattr(
        "internal.ops.readiness._learning_loop_health",
        lambda: {"status": "ok", "ledger": {"gap": False}},
    )
    monkeypatch.setattr(
        "internal.worker_peer.get_worker_peer",
        lambda: {"expected": False, "alive": None},
    )
    monkeypatch.setattr("internal.run_mode.inline_worker_expected", lambda: False)
    monkeypatch.setattr("internal.run_mode.is_worker_mode", lambda: False)
    monkeypatch.setattr("internal.run_mode.split_worker_v2_enabled", lambda: False)
    monkeypatch.setattr("internal.run_mode.worker_mode_label", lambda: "combined")
    monkeypatch.setattr("fetchers.taostats_client.is_available", lambda: True)


def test_readiness_keeps_no_graded_picks_visible_but_nonblocking(monkeypatch):
    _patch_healthy_readiness_dependencies(monkeypatch, graded=0)

    from internal.ops.readiness import build_readiness_report

    report = build_readiness_report()

    assert report["ready"] is True
    assert report["status"] == "ready"
    assert "learning_loop_has_no_graded_picks" in report["issues"]
    assert "learning_loop_has_no_graded_picks" in report["advisories"]
    assert report["blocking_issues"] == []


def test_readiness_keeps_resolver_failure_blocking_when_no_picks_are_graded(monkeypatch):
    _patch_healthy_readiness_dependencies(monkeypatch, resolver_running=False, graded=0)

    from internal.ops.readiness import build_readiness_report

    report = build_readiness_report()

    assert report["ready"] is False
    assert report["status"] == "degraded"
    assert "prediction_resolver_not_running" in report["blocking_issues"]
    assert "learning_loop_has_no_graded_picks" in report["advisories"]
