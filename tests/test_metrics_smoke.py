"""Smoke checks for Prometheus /metrics exposition."""

import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from server import app


def test_refresh_complete_gauge_unavailable_without_cache(monkeypatch, tmp_path):
    from internal.metrics import (
        LIVE_REFRESH_COMPLETE,
        LIVE_REFRESH_COMPLETE_UNAVAILABLE,
        refresh_from_state,
    )

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "nodata"))
    monkeypatch.setattr("internal.data_volume.worker_data_freshness", lambda: None)
    LIVE_REFRESH_COMPLETE.set(1.0)
    refresh_from_state()
    assert LIVE_REFRESH_COMPLETE._value.get() == LIVE_REFRESH_COMPLETE_UNAVAILABLE


def test_refresh_complete_gauge_legacy_cache_without_field(monkeypatch, tmp_path):
    from internal.metrics import LIVE_REFRESH_COMPLETE, refresh_from_state

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    now = datetime.now(timezone.utc).isoformat()
    (tmp_path / "live_subnets.json").write_text(
        json.dumps({"synced_at": now, "count": 1, "subnets": [{"netuid": 1}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr("internal.data_volume.worker_data_freshness", lambda: None)
    refresh_from_state()
    assert LIVE_REFRESH_COMPLETE._value.get() == 1.0


def test_metrics_exposes_http_and_freshness_gauges():
    with TestClient(app) as client:
        response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert "requests_total" in body or "request_processing_time" in body
    assert "subnet_live_stale" in body or "subnet_scheduler_running" in body
    assert "subnet_live_refresh_complete" in body
