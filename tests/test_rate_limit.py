"""Smoke tests for slowapi rate limiting (audit #9)."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def rate_limited_client(monkeypatch):
    monkeypatch.setenv("ENABLE_RATE_LIMIT", "1")
    monkeypatch.setenv("RATE_LIMIT_DEFAULT", "2/minute")
    import internal.rate_limit as rl

    rl._limiter = None
    import server

    importlib.reload(server)
    yield TestClient(server.app)
    rl._limiter = None


def test_under_limit_returns_200(rate_limited_client):
    for _ in range(2):
        assert rate_limited_client.get("/api/registry").status_code == 200


def test_exempt_health_never_429(rate_limited_client):
    for _ in range(10):
        assert rate_limited_client.get("/health").status_code == 200


def test_over_limit_returns_429(rate_limited_client):
    for _ in range(2):
        rate_limited_client.get("/api/registry")
    assert rate_limited_client.get("/api/registry").status_code == 429
