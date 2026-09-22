"""Homepage Cache-Control: handler no-store survives middleware; warm shell is public."""

import time

from fastapi.testclient import TestClient

import server


def test_cold_homepage_keeps_no_store(monkeypatch):
    # TTL 0 makes any in-process shell a miss, including one a boot thread just filled.
    monkeypatch.setattr(server, "HOMEPAGE_SHELL_CACHE_SECONDS", 0)
    with TestClient(server.app) as client:
        server._HOMEPAGE_HTML_CACHE["html"] = None
        server._HOMEPAGE_HTML_CACHE["at"] = 0.0
        response = client.get("/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"


def test_warm_homepage_gets_public_ttl():
    with TestClient(server.app) as client:
        server._HOMEPAGE_HTML_CACHE["html"] = "<html>warm</html>"
        server._HOMEPAGE_HTML_CACHE["at"] = time.time()
        response = client.get("/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=60"


def test_api_cache_policy_unchanged():
    with TestClient(server.app) as client:
        response = client.get("/api/registry")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=30"
