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
