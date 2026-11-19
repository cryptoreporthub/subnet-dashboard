"""Homepage Cache-Control: handler no-store survives middleware; warm shell is public."""

from contextlib import asynccontextmanager
import time

from fastapi.testclient import TestClient
import pytest

import server


@pytest.fixture
def client(monkeypatch):
    @asynccontextmanager
    async def no_lifespan(_app):
        yield

    monkeypatch.setattr(server.app.router, "lifespan_context", no_lifespan)
    monkeypatch.setattr(server, "_schedule_homepage_warm", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "_prime_emergency_home_html", lambda: None)
    monkeypatch.setattr(server, "load_data", lambda path: {})
    monkeypatch.setattr(server, "load_subnets_source", lambda timeout=None: [])
    monkeypatch.setattr("internal.subnet_names._tmc_display_names", lambda: {})
    monkeypatch.setattr("internal.subnet_names._load_name_overrides", lambda: {})
    monkeypatch.setattr("internal.subnet_names._load_local_registry", lambda: {})
    monkeypatch.setattr("internal.subnet_names._remote_registry", lambda: {})
    monkeypatch.setattr("internal.subnets.feed._load_subnets_inner", lambda: [])
    with TestClient(server.app) as test_client:
        yield test_client


def test_cold_homepage_keeps_no_store(client, monkeypatch):
    # TTL 0 makes any in-process shell a miss, including one a boot thread just filled.
    monkeypatch.setattr(server, "HOMEPAGE_SHELL_CACHE_SECONDS", 0)
    monkeypatch.setattr(server, "_HOMEPAGE_HTML_CACHE", {"at": 0.0, "html": None})
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"


def test_warm_homepage_gets_public_ttl(client, monkeypatch):
    monkeypatch.setattr(server, "_HOMEPAGE_HTML_CACHE", {"at": 0.0, "html": None})
    server._HOMEPAGE_HTML_CACHE["html"] = "<html>warm</html>"
    server._HOMEPAGE_HTML_CACHE["at"] = time.time()
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60"


def test_api_cache_policy_unchanged(client):
    response = client.get("/api/registry")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=30"
