"""A warm homepage shell stays edge-cacheable. A cold shell does not."""

import time

from fastapi.testclient import TestClient

import server
from server import app


def test_homepage_cache_control_public():
    with TestClient(app) as client:
        server._HOMEPAGE_HTML_CACHE["html"] = "<html>warm</html>"
        server._HOMEPAGE_HTML_CACHE["at"] = time.time()
        resp = client.get("/")
    assert resp.status_code == 200
    cc = resp.headers.get("Cache-Control", "")
    assert "public" in cc
    assert "max-age=60" in cc


def test_homepage_cache_control_no_store_on_cold_miss():
    with TestClient(app) as client:
        server._HOMEPAGE_HTML_CACHE["html"] = ""
        server._HOMEPAGE_HTML_CACHE["at"] = 0.0
        resp = client.get("/")
    assert resp.status_code == 200
    cc = resp.headers.get("Cache-Control", "")
    assert "no-store" in cc
    assert "max-age=0" in cc
    assert "public" not in cc
