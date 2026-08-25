"""Smoke checks for Prometheus /metrics exposition."""

from fastapi.testclient import TestClient

from server import app


def test_metrics_exposes_http_and_freshness_gauges():
    with TestClient(app) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert "requests_total" in body or "request_processing_time" in body
    assert "subnet_live_stale" in body or "subnet_scheduler_running" in body


def test_inline_worker_metrics_use_worker_peer_for_scheduler_liveness(monkeypatch):
    from internal import metrics

    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("INLINE_WORKER", "1")
    monkeypatch.delenv("WORKER_SPLIT_V2", raising=False)
    peer = {"alive": True, "peer": "inline_worker", "source": "file"}
    monkeypatch.setattr("internal.worker_peer.get_worker_peer", lambda: peer)
    monkeypatch.setattr(
        "internal.live_subnets.live_data_freshness",
        lambda: {"age_seconds": 12, "stale": False},
    )
    monkeypatch.setattr(
        "internal.freshness.get_sync_state",
        lambda: {
            "background_running": False,
            "last_sync_ok": None,
            "freshness": {},
        },
    )
    monkeypatch.setattr(
        metrics,
        "_resolver_state",
        lambda: {"running": False, "last_run_ok": False},
    )
    monkeypatch.setattr(
        metrics,
        "_adversarial_state",
        lambda: {"running": False, "last_run_ok": False},
    )
    monkeypatch.setattr(
        "internal.job_scheduler.state",
        lambda: {"running": False, "job_count": 0},
    )

    metrics.refresh_from_state()

    assert metrics.SYNC_RUNNING._value.get() == 1
    assert metrics.SYNC_LAST_OK._value.get() == 1
    assert metrics.SCHEDULER_RUNNING.labels(scheduler="resolver")._value.get() == 1
    assert metrics.SCHEDULER_RUNNING.labels(scheduler="adversarial")._value.get() == 1
    assert metrics.SCHEDULER_RUNNING.labels(scheduler="apscheduler")._value.get() == 1

    peer["alive"] = False
    metrics.refresh_from_state()

    assert metrics.SYNC_RUNNING._value.get() == 0
    assert metrics.SYNC_LAST_OK._value.get() == 0
    assert metrics.SCHEDULER_RUNNING.labels(scheduler="resolver")._value.get() == 0
    assert metrics.SCHEDULER_RUNNING.labels(scheduler="adversarial")._value.get() == 0
    assert metrics.SCHEDULER_RUNNING.labels(scheduler="apscheduler")._value.get() == 0


def test_inline_worker_metrics_mark_stale_shared_cache_unhealthy(monkeypatch):
    from internal import metrics

    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("INLINE_WORKER", "1")
    monkeypatch.delenv("WORKER_SPLIT_V2", raising=False)
    monkeypatch.setattr(
        "internal.worker_peer.get_worker_peer",
        lambda: {"alive": True, "peer": "inline_worker", "source": "file"},
    )
    monkeypatch.setattr(
        "internal.live_subnets.live_data_freshness",
        lambda: {"age_seconds": 999, "stale": True},
    )
    monkeypatch.setattr(
        "internal.freshness.get_sync_state",
        lambda: {"background_running": False, "last_sync_ok": None, "freshness": {}},
    )

    metrics.refresh_from_state()

    assert metrics.SYNC_RUNNING._value.get() == 1
    assert metrics.SYNC_LAST_OK._value.get() == 0
