"""§17.F1 — watchlist API."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from internal.watchlist import store as watchlist_store
from server import app


def test_watchlist_get_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_LISTENER_BETA_BYPASS", "1")
    path = tmp_path / "watchlist.json"
    monkeypatch.setattr(watchlist_store, "WATCHLIST_PATH", str(path))
    client = TestClient(app)
    resp = client.get("/api/watchlist")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["netuids"] == []


def test_watchlist_put_and_get(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_LISTENER_BETA_BYPASS", "1")
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
    assert disk["profiles"]


def test_watchlist_threshold_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_LISTENER_BETA_BYPASS", "1")
    path = tmp_path / "watchlist.json"
    monkeypatch.setattr(watchlist_store, "WATCHLIST_PATH", str(path))
    client = TestClient(app)
    client.put("/api/watchlist", json={"netuids": [7]})
    resp = client.put("/api/watchlist/thresholds", json={"netuid": 7, "threshold": 72.5})
    assert resp.status_code == 200
    assert resp.json()["thresholds"]["7"] == 72.5
    got = client.get("/api/watchlist/thresholds")
    assert got.json()["thresholds"]["7"] == 72.5


def test_watchlist_is_open_without_a_premium_gate(monkeypatch, tmp_path):
    monkeypatch.delenv("TELEGRAM_LISTENER_BETA_BYPASS", raising=False)
    monkeypatch.setattr(watchlist_store, "WATCHLIST_PATH", str(tmp_path / "watchlist.json"))
    resp = TestClient(app).get("/api/watchlist")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_owner_profiles_are_isolated_and_partial_writes_preserve_alerts(tmp_path):
    path = str(tmp_path / "watchlist.json")
    watchlist_store.save_watchlist(
        [7],
        path=path,
        thresholds={"7": 72.5},
        alerts={"telegram:id:a": {"enabled": True}},
        owner="browser:a",
    )
    watchlist_store.save_watchlist([9], path=path, owner="browser:b")
    first = watchlist_store.load_watchlist(path=path, owner="browser:a")
    second = watchlist_store.load_watchlist(path=path, owner="browser:b")
    assert first["netuids"] == [7]
    assert first["thresholds"]["7"] == 72.5
    assert first["alerts"]["telegram:id:a"]["enabled"] is True
    assert second["netuids"] == [9]
    assert second["alerts"] == {}
