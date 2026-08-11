"""Homepage shell must be edge-cacheable to absorb concurrent bursts."""

from fastapi.testclient import TestClient

from server import app


def test_homepage_cache_control_public():
    with TestClient(app) as client:
        resp = client.get("/")
    assert resp.status_code == 200
    cc = resp.headers.get("Cache-Control", "")
    assert "public" in cc
    assert "max-age=60" in cc
