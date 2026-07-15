"""§17.F1 — watchlist API."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from internal.watchlist import store as watchlist_store
from server import app


def test_watchlist_get_empty(monkeypatch, tmp_path):
    path = tmp_path / "watchlist.json"
    monkeypatch.setattr(watchlist_store, "WATCHLIST_PATH", str(path))
    client = TestClient(app)
    resp = client.get("/api/watchlist")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["netuids"] == []


def test_watchlist_put_and_get(monkeypatch, tmp_path):
    path = tmp_path / "watchlist.json"
    monkeypatch.setattr(watchlist_store, "WATCHLIST_PATH", str(path))
    client = TestClient(app)
    put = client.put("/api/watchlist", json={"netuids": [3, 3, 19, -1, "x", 7]})
    assert put.status_code == 200
    assert put.json()["netuids"] == [3, 19, 7]

    got = client.get("/api/watchlist")
    assert got.status_code == 200
    assert got.json()["netuids"] == [3, 19, 7]
    assert path.exists()
    disk = json.loads(path.read_text())
    assert disk["netuids"] == [3, 19, 7]
