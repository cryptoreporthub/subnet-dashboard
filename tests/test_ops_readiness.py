"""§33 — production readiness probe."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from server import app

client = TestClient(app)


def _assert_no_sensitive_tracker_fields(trackers: dict) -> None:
    for snap in (trackers or {}).values():
        assert "last_error" not in snap
        assert "last_evidence" not in snap


def _seed_tracker_with_sensitive_fields(name: str = "shield_audit_tracker") -> None:
    from internal.liveness import LivenessTracker

    tracker = LivenessTracker(name, interval_seconds=60, persist=False)
    tracker.record_success(evidence={"scanned": 1, "path": "/secret/artifact"})
    tracker.record_failure(error="internal stack trace must not leak")


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
        "ledger": {"gap": False},
    }
    remote_liveness = {
        "trackers": {
            "prediction_resolver": {
                "name": "prediction_resolver",
                "lifecycle": "started",
                "status": "ok",
                "last_event_at": "2026-07-29T12:00:00+00:00",
                "last_success_at": "2026-07-29T12:00:00+00:00",
                "success_age_seconds": 30.0,
                "source": "inprocess",
            }
        },
        "checked_at": "2026-07-29T12:00:30+00:00",
        "source": "inprocess",
    }

    def _proxy(path, **_kwargs):
        if path == "/api/liveness":
            return remote_liveness
        return remote_health

    with patch("internal.worker_proxy.fetch_worker_json_sync", side_effect=_proxy):
        with patch(
            "internal.worker_peer.get_worker_peer",
            return_value={"expected": True, "alive": True, "peer": "dedicated_worker"},
        ):
            from internal.ops.readiness import build_readiness_report

            report = build_readiness_report()
    assert report["resolver"]["running"] is True
    assert report["resolver"]["peer"] == "dedicated_worker"
    assert report["resolver"]["status"] == "ok"
    assert "prediction_resolver_not_running" not in report["issues"]
    assert "liveness" in report
    assert report["liveness"]["trackers"]["prediction_resolver"]["status"] == "ok"


def test_readiness_pump_desk_trust_from_liveness_registry(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    from internal.liveness import LivenessTracker

    tracker = LivenessTracker("pump_ladder", interval_seconds=60, persist=False)
    tracker.record_success(evidence={"scanned": 3})
    from internal.ops.readiness import build_readiness_report

    report = build_readiness_report()
    trust = report["pump_desk_trust"]
    assert trust["ready"] is True
    assert trust["liveness_status"] == "ok"
    assert trust["source"] == "liveness_registry"


def test_readiness_pump_desk_trust_not_ready_when_stale(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    from internal.liveness import LivenessTracker

    tracker = LivenessTracker("pump_ladder", interval_seconds=60, persist=False)
    tracker.record_success(evidence={"scanned": 1})
    tracker._last_success_epoch -= 600
    from internal.ops.readiness import build_readiness_report

    report = build_readiness_report()
    assert report["pump_desk_trust"]["ready"] is False
    assert report["pump_desk_trust"]["liveness_status"] == "stale"


def test_api_liveness_returns_registry():
    resp = client.get("/api/liveness")
    assert resp.status_code == 200
    body = resp.json()
    assert "trackers" in body
    assert "checked_at" in body
    assert isinstance(body["trackers"], dict)


def test_api_liveness_strips_sensitive_tracker_fields(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    _seed_tracker_with_sensitive_fields()
    resp = client.get("/api/liveness")
    assert resp.status_code == 200
    _assert_no_sensitive_tracker_fields(resp.json().get("trackers"))


def test_api_readiness_strips_sensitive_liveness_fields(monkeypatch):
    monkeypatch.setenv("RUN_MODE", "web")
    _seed_tracker_with_sensitive_fields("shield_readiness_tracker")
    resp = client.get("/api/ops/readiness")
    assert resp.status_code == 200
    body = resp.json()
    _assert_no_sensitive_tracker_fields((body.get("liveness") or {}).get("trackers"))
    assert "last_error" not in body.get("resolver", {})
    assert "last_evidence" not in body.get("resolver", {})
    assert "last_error" not in body.get("pump_desk_trust", {})
    assert "last_evidence" not in body.get("pump_desk_trust", {})


def test_ops_readiness_contract():
    resp = client.get("/api/ops/readiness")
    assert resp.status_code == 200
    body = resp.json()
    assert "ready" in body
    assert "issues" in body
    assert "learning" in body
    assert "resolver" in body
    assert "liveness" in body
    assert "pump_desk_trust" in body
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
