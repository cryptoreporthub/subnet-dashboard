"""Static asset Cache-Control must not pin unfingerprinted CSS/JS for a year."""

from fastapi.testclient import TestClient

from server import app


def test_static_css_cache_control_not_immutable():
    with TestClient(app) as client:
        resp = client.get("/static/css/ui.css")
    assert resp.status_code == 200
    cc = resp.headers.get("Cache-Control", "")
    assert "immutable" not in cc
    assert "max-age=300" in cc
    assert "must-revalidate" in cc
