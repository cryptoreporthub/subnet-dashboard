"""§17.F1/F2 — home watchlist + conviction alert UI."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from internal.analytics.home_habit import conviction_alerts_snapshot, watchlist_snapshot
from internal.watchlist import store as watchlist_store
from server import app


def test_watchlist_snapshot_empty(monkeypatch, tmp_path):
    path = tmp_path / "watchlist.json"
    monkeypatch.setattr(watchlist_store, "WATCHLIST_PATH", str(path))
    snap = watchlist_snapshot()
    assert snap["status"] == "ok"
    assert snap["netuids"] == []
    assert snap["count"] == 0


def test_index_home_habit_controls():
    with TestClient(app) as client:
        html = client.get("/").text
    assert 'id="habit-pin-btn"' in html
    assert 'id="habit-alert-btn"' in html
    assert "watchlist_alerts.js" in html
    assert "habit-watchlist-summary" in html


def test_pin_button_updates_watchlist(monkeypatch, tmp_path):
    path = tmp_path / "watchlist.json"
    monkeypatch.setattr(watchlist_store, "WATCHLIST_PATH", str(path))
    client = TestClient(app)
    put = client.put("/api/watchlist", json={"netuids": [12]})
    assert put.status_code == 200
    assert json.loads(path.read_text())["netuids"] == [12]
