"""Smoke tests for slowapi rate limiting (audit #9, #1633)."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import internal.rate_limit as rl
from internal.rate_limit import client_ip


@pytest.fixture
def rate_limited_client(monkeypatch):
    monkeypatch.setenv("ENABLE_RATE_LIMIT", "1")
    monkeypatch.setenv("RATE_LIMIT_DEFAULT", "2/minute")
    rl._limiter = None
    import server

    importlib.reload(server)
    yield TestClient(server.app)
    rl._limiter = None


@pytest.fixture
def fly_rate_limited_client(monkeypatch):
    monkeypatch.setenv("FLY_APP_NAME", "subnet-dashboard")
    monkeypatch.setenv("ENABLE_RATE_LIMIT", "1")
    monkeypatch.setenv("RATE_LIMIT_DEFAULT", "2/minute")
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


def test_fly_rotating_xff_shares_bucket_gets_429(fly_rate_limited_client):
    fixed_fly = "203.0.113.50"
    headers = {"Fly-Client-IP": fixed_fly}
    for i in range(2):
        fly_rate_limited_client.get(
            "/api/registry",
            headers={**headers, "X-Forwarded-For": f"198.51.100.{i}"},
        )
    assert (
        fly_rate_limited_client.get(
            "/api/registry",
            headers={**headers, "X-Forwarded-For": "198.51.100.99"},
        ).status_code
        == 429
    )


def test_fly_distinct_fly_client_ips_separate_buckets(fly_rate_limited_client):
    for ip in ("203.0.113.1", "203.0.113.2"):
        for _ in range(2):
            assert (
                fly_rate_limited_client.get("/api/registry", headers={"Fly-Client-IP": ip}).status_code
                == 200
            )


def test_fly_missing_fly_header_xff_does_not_split_bucket(fly_rate_limited_client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DEFAULT", "2/minute")
    rl._limiter = None
    import server

    importlib.reload(server)
    client = TestClient(server.app)
    for i in range(2):
        client.get("/api/registry", headers={"X-Forwarded-For": f"10.0.0.{i}"})
    assert client.get("/api/registry", headers={"X-Forwarded-For": "10.0.0.99"}).status_code == 429


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
