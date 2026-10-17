"""Smoke tests for slowapi rate limiting (audit #9).

Runs against a throwaway FastAPI app. An earlier version reloaded the product ``server`` module
with RATE_LIMIT_DEFAULT=2/minute and never restored it, so every later test that used
``server.app`` inherited a 2-requests-per-minute limiter and failed with 429.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def rate_limited_client(monkeypatch):
    monkeypatch.setenv("ENABLE_RATE_LIMIT", "1")
    monkeypatch.setenv("RATE_LIMIT_DEFAULT", "2/minute")
    import internal.rate_limit as rl

    previous = rl._limiter
    rl._limiter = None
    app = FastAPI()

    @app.get("/api/registry")
    def registry():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"ok": True}

    rl.mount_rate_limit(app)
    yield TestClient(app)
    rl._limiter = previous


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


def test_limit_test_does_not_replace_the_product_limiter():
    """The product limiter singleton must survive these tests unchanged."""
    import internal.rate_limit as rl
    from server import app

    assert app.state.limiter is rl._limiter
