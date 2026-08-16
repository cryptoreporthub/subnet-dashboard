"""Layout preview for missing listener glances — not wired into the live desk."""

from fastapi.testclient import TestClient

from server import app

client = TestClient(app)


def test_listener_gap_preview_is_sample_layout():
    r = client.get("/preview/listener-gaps")
    assert r.status_code == 200
    html = r.text
    assert "LAYOUT PREVIEW" in html
    assert "SAMPLE" in html
    assert "Signature proof receipt" in html
    assert "Net-flow pool" in html
    assert "Multi-horizon projection" in html
    assert "not live" in html.lower() or "sample numbers, not live" in html.lower()
    assert 'data-hydrate' in html
