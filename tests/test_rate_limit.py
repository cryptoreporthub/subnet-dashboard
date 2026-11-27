"""Smoke tests for slowapi rate limiting (audit #9, #1633)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

import internal.rate_limit as rl
import server
from internal.rate_limit import client_ip, default_limit


def _restore_limiter_env(monkeypatch, prev_default, prev_fly):
    if prev_default is None:
        os.environ.pop("RATE_LIMIT_DEFAULT", None)
    else:
        os.environ["RATE_LIMIT_DEFAULT"] = prev_default
    if prev_fly is None:
        os.environ.pop("FLY_APP_NAME", None)
    elif prev_fly:
        os.environ["FLY_APP_NAME"] = prev_fly
    monkeypatch.setattr(rl, "_limiter", None)
    lim = rl.get_limiter()
    assert lim is not None
    assert default_limit() == os.environ.get("RATE_LIMIT_DEFAULT", "120/minute")
    server.app.state.limiter = lim
    lim.reset()


@pytest.fixture
def rate_limited_client(monkeypatch, request):
    """2/min limiter; optional fly mode via @pytest.mark.parametrize(..., indirect=True)."""
    on_fly = getattr(request, "param", False)
    monkeypatch.setenv("ENABLE_RATE_LIMIT", "1")
    prev_default = os.environ.get("RATE_LIMIT_DEFAULT")
    prev_fly = os.environ.get("FLY_APP_NAME")
    os.environ["RATE_LIMIT_DEFAULT"] = "2/minute"
    if on_fly:
        os.environ["FLY_APP_NAME"] = "subnet-dashboard"
    else:
        os.environ.pop("FLY_APP_NAME", None)
    monkeypatch.setattr(rl, "_limiter", None)
    lim = rl.get_limiter()
    server.app.state.limiter = lim
    yield TestClient(server.app)
    _restore_limiter_env(monkeypatch, prev_default, prev_fly)


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

        client = type("C", (), {"host": "203.0.113.9"})()

    assert client_ip(_Req()) == "203.0.113.9"


def test_fly_client_ip_header_strips_whitespace(monkeypatch):
    monkeypatch.setenv("FLY_APP_NAME", "subnet-dashboard")
    from starlette.datastructures import Headers

    class _Req:
        headers = Headers({"Fly-Client-IP": "  203.0.113.77  "})

        client = type("C", (), {"host": "127.0.0.1"})()

    assert client_ip(_Req()) == "203.0.113.77"


def test_off_fly_xff_ignored_for_key(monkeypatch):
    monkeypatch.delenv("FLY_APP_NAME", raising=False)

    class _Req:
        headers = {"X-Forwarded-For": "1.2.3.4", "Fly-Client-IP": "9.9.9.9"}

        client = type("C", (), {"host": "127.0.0.1"})()

    assert client_ip(_Req()) == "127.0.0.1"


def test_off_fly_forged_xff_still_one_bucket(rate_limited_client):
    for i in range(2):
        rate_limited_client.get("/api/registry", headers={"X-Forwarded-For": f"198.51.100.{i}"})
    assert (
        rate_limited_client.get("/api/registry", headers={"X-Forwarded-For": "198.51.100.99"}).status_code
        == 429
    )