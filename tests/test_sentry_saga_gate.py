"""Saga P1 gate — local runtime verification for saga-route Sentry capture.

Synthetic prod verify (fly machine exec) was skipped: no flyctl MCP on this VM.
These tests substitute with TestClient + capture transport (Starlette request context).
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
import sentry_sdk
from fastapi.testclient import TestClient
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from internal.sentry_setup import before_send
from server import app


@pytest.fixture
def sentry_capture(monkeypatch):
    captured: list[dict] = []

    def _capture(event, hint):
        out = before_send(event, hint)
        if out is not None:
            captured.append(out)
        return out

    monkeypatch.setenv("SENTRY_DSN", "https://examplePublicKey@o0.ingest.sentry.io/0")
    sentry_sdk.init(
        dsn="https://examplePublicKey@o0.ingest.sentry.io/0",
        integrations=[
            LoggingIntegration(level=logging.INFO, event_level=logging.WARNING),
            StarletteIntegration(),
            FastApiIntegration(),
        ],
        before_send=_capture,
        transport=lambda: None,
        environment="test",
    )
    yield captured
    sentry_sdk.flush()


@pytest.fixture
def client():
    return TestClient(app)


def test_saga_gate_subnetsummer_route_failure_attaches_request_url(sentry_capture, client):
    with patch(
        "internal.share_pages.routes._listener_page_context",
        side_effect=RuntimeError("saga-gate synthetic"),
    ):
        resp = client.get("/subnetsummer")
    assert resp.status_code == 200
    assert sentry_capture
    urls = [e.get("request", {}).get("url", "") for e in sentry_capture]
    assert any("/subnetsummer" in u for u in urls)


def test_saga_gate_pump_alerts_warning_attaches_request_url(sentry_capture, client):
    """Split_v2 proxy path: worker fetch failure logs warning with request URL attached."""
    with patch("internal.data_volume.needs_worker_volume_proxy", return_value=True), patch(
        "internal.worker_proxy._fetch_worker_http",
        side_effect=ConnectionError("saga-gate synthetic"),
    ):
        resp = client.get("/api/pump-alerts")
    assert resp.status_code == 200
    pump_events = [
        e
        for e in sentry_capture
        if "/api/pump-alerts" in (e.get("request", {}).get("url") or "")
        or (e.get("logentry", {}).get("params") or [None])[0] == "/api/pump-alerts"
    ]
    assert pump_events


def test_saga_gate_before_send_subnetsummer_mock_event():
    event = {
        "logger": "internal.share_pages.routes",
        "level": "error",
        "logentry": {
            "message": "listener page context outer failed: %s",
            "params": ("boom",),
        },
        "request": {"url": "http://test/subnetsummer"},
    }
    result = before_send(event, {})
    assert result is not None
    assert "/subnetsummer" in result["request"]["url"]
