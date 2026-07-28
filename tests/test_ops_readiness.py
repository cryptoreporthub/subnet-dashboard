"""§33 — production readiness probe."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from server import app

client = TestClient(app)


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
