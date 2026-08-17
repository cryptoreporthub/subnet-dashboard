"""Static asset Cache-Control is immutable because every URL is cache-busted via ?v={{ static_v }}."""

from fastapi.testclient import TestClient

from server import app


def test_static_css_cache_control_immutable():
    with TestClient(app) as client:
        resp = client.get("/static/css/ui.css")
    assert resp.status_code == 200
    cc = resp.headers.get("Cache-Control", "")
    assert "public" in cc
    assert "max-age=31536000" in cc
    assert "immutable" in cc


def test_static_js_cache_control_immutable():
    with TestClient(app) as client:
        resp = client.get("/static/js/cockpit_hydrate.js")
    assert resp.status_code == 200
    cc = resp.headers.get("Cache-Control", "")
    assert "public" in cc
    assert "max-age=31536000" in cc
    assert "immutable" in cc
