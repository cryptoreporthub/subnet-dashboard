"""Smoke tests for slowapi rate limiting (audit #9)."""

from __future__ import annotations

import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def rate_limited_client(monkeypatch):
    import internal.rate_limit as rl
    import server

    monkeypatch.setenv("ENABLE_RATE_LIMIT", "1")
    prev_default = os.environ.get("RATE_LIMIT_DEFAULT")
    # ponytail: os.environ not monkeypatch.setenv — pytest undo restores 2/minute and later
    # tests see [200,200,429,429,429,429] on registry (rate_limit leak).
    os.environ["RATE_LIMIT_DEFAULT"] = "2/minute"
    monkeypatch.setattr(rl, "_limiter", None)
    importlib.reload(server)
    yield TestClient(server.app)
    if prev_default is None:
        os.environ.pop("RATE_LIMIT_DEFAULT", None)
    else:
        os.environ["RATE_LIMIT_DEFAULT"] = prev_default
    monkeypatch.setattr(rl, "_limiter", None)
    import internal.learning.routes as learning_routes

    importlib.reload(learning_routes)
    importlib.reload(server)
    lim = rl.get_limiter()
    if lim is not None:
        server.app.state.limiter = lim
        lim.reset()


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
