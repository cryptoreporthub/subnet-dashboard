"""Smoke tests for slowapi rate limiting (audit #9, #1633)."""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import internal.rate_limit as rl
import server
from internal.rate_limit import client_ip, default_limit, limit_or_noop, mount_rate_limit


def _build_isolated_rate_limit_app(*, registry_limit: str = "2/minute") -> FastAPI:
    """Fresh FastAPI — never mutates global server.app (G2 / ENABLE_RATE_LIMIT=0 safe)."""
    rl._limiter = None
    app = FastAPI()
    mount_rate_limit(app)

    @app.get("/api/registry")
    @limit_or_noop(registry_limit, override_defaults=True)
    def _registry(request: Request):
        return []

    @app.get("/health")
    def _health():
        return "OK"

    return app


@pytest.fixture
def rate_limited_client(monkeypatch, request):
    """2/min limiter on isolated app; optional fly mode via @pytest.mark.parametrize(..., indirect=True)."""
    on_fly = getattr(request, "param", False)
    prev_enable = os.environ.get("ENABLE_RATE_LIMIT")
    prev_default = os.environ.get("RATE_LIMIT_DEFAULT")
    prev_fly = os.environ.get("FLY_APP_NAME")
    monkeypatch.setenv("ENABLE_RATE_LIMIT", "1")
    os.environ["RATE_LIMIT_DEFAULT"] = "2/minute"
    if on_fly:
        os.environ["FLY_APP_NAME"] = "subnet-dashboard"
    else:
        os.environ.pop("FLY_APP_NAME", None)
    app = _build_isolated_rate_limit_app()
    yield TestClient(app)
    if prev_enable is None:
        os.environ.pop("ENABLE_RATE_LIMIT", None)
    else:
        os.environ["ENABLE_RATE_LIMIT"] = prev_enable
    if prev_default is None:
        os.environ.pop("RATE_LIMIT_DEFAULT", None)
    else:
        os.environ["RATE_LIMIT_DEFAULT"] = prev_default
    if prev_fly is None:
        os.environ.pop("FLY_APP_NAME", None)
    else:
        os.environ["FLY_APP_NAME"] = prev_fly
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


@pytest.mark.parametrize("rate_limited_client", [True], indirect=True)
def test_fly_rotating_xff_shares_bucket_gets_429(rate_limited_client):
    fixed_fly = "203.0.113.50"
    headers = {"Fly-Client-IP": fixed_fly}
    for i in range(2):
        rate_limited_client.get(
            "/api/registry",
            headers={**headers, "X-Forwarded-For": f"198.51.100.{i}"},
        )
    assert (
        rate_limited_client.get(
            "/api/registry",
            headers={**headers, "X-Forwarded-For": "198.51.100.99"},
        ).status_code
        == 429
    )


@pytest.mark.parametrize("rate_limited_client", [True], indirect=True)
def test_fly_distinct_fly_client_ips_separate_buckets(rate_limited_client):
    for ip in ("203.0.113.1", "203.0.113.2"):
        for _ in range(2):
            assert (
                rate_limited_client.get("/api/registry", headers={"Fly-Client-IP": ip}).status_code == 200
            )


@pytest.mark.parametrize("rate_limited_client", [True], indirect=True)
def test_fly_missing_fly_header_xff_does_not_split_bucket(rate_limited_client):
    for i in range(2):
        rate_limited_client.get("/api/registry", headers={"X-Forwarded-For": f"10.0.0.{i}"})
    assert rate_limited_client.get("/api/registry", headers={"X-Forwarded-For": "10.0.0.99"}).status_code == 429


def test_fly_missing_header_ignores_xff_for_key(monkeypatch):
    monkeypatch.setenv("FLY_APP_NAME", "subnet-dashboard")

    class _Req:
        headers = {"X-Forwarded-For": "1.1.1.1, 9.9.9.9"}
        scope = {"client": ("203.0.113.9", 12345)}

    assert client_ip(_Req()) == "203.0.113.9"


def test_fly_client_ip_header_strips_whitespace(monkeypatch):
    monkeypatch.setenv("FLY_APP_NAME", "subnet-dashboard")
    from starlette.datastructures import Headers

    class _Req:
        headers = Headers({"Fly-Client-IP": "  203.0.113.77  "})
        scope = {"client": ("127.0.0.1", 12345)}

    assert client_ip(_Req()) == "203.0.113.77"


def test_off_fly_xff_ignored_for_key(monkeypatch):
    monkeypatch.delenv("FLY_APP_NAME", raising=False)

    class _Req:
        headers = {"X-Forwarded-For": "1.2.3.4", "Fly-Client-IP": "9.9.9.9"}
        scope = {"client": ("10.20.30.40", 12345)}

    assert client_ip(_Req()) == "10.20.30.40"


def test_off_fly_forged_xff_still_one_bucket(rate_limited_client):
    for i in range(2):
        rate_limited_client.get("/api/registry", headers={"X-Forwarded-For": f"198.51.100.{i}"})
    assert (
        rate_limited_client.get("/api/registry", headers={"X-Forwarded-For": "198.51.100.99"}).status_code
        == 429
    )


def test_rate_limit_module_does_not_mount_on_global_server():
    """Importing this module must not attach SlowAPI to server.app (hermetic under ENABLE_RATE_LIMIT=0)."""
    assert not getattr(server.app.state, "_rate_limit_fixture_mounted", False)


def test_isolated_fixture_teardown_restores_default_env(monkeypatch):
    """After fixture env, default_limit() matches restored env (no server.app singleton leak)."""
    monkeypatch.setenv("ENABLE_RATE_LIMIT", "1")
    monkeypatch.delenv("RATE_LIMIT_DEFAULT", raising=False)
    assert default_limit() == "120/minute"
    app = _build_isolated_rate_limit_app(registry_limit="120/minute")
    client = TestClient(app)
    for _ in range(3):
        assert client.get("/api/registry").status_code == 200