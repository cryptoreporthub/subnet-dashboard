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
