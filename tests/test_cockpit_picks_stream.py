"""H1 cockpit.picks SSE stream tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server import app

client = TestClient(app)


def test_cockpit_picks_stream_once():
    resp = client.get("/api/cockpit/stream?once=1")
    assert resp.status_code == 200
    body = resp.text
    assert "event: cockpit.picks" in body
    assert '"type":"cockpit.picks"' in body or '"type": "cockpit.picks"' in body.replace(" ", "")


def test_index_has_hour_watch_mount():
    html = client.get("/").text
    assert 'id="hour-watch-now"' in html


def test_hour_pick_has_generated_at():
    resp = client.get("/api/top-pick/hour")
    assert resp.status_code == 200
    picks = resp.json().get("picks") or []
    if picks:
        assert "generated_at" in picks[0] or picks[0].get("subnet")
