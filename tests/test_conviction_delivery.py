"""§17.F2 — conviction alert delivery."""

from __future__ import annotations

import json

from internal.conviction_alerts import delivery as deliv
from internal.watchlist import store as watchlist_store


def test_delivery_off_by_default(monkeypatch):
    monkeypatch.delenv("CONVICTION_ALERT_DELIVERY", raising=False)
    out = deliv.deliver_alerts([{"message": "x", "subnet_id": 1, "dedupe_key": "k"}])
    assert out["mode"] == "off"
    assert out["delivered"] == 0


def test_dry_run_records_without_network(monkeypatch, tmp_path):
    monkeypatch.setenv("CONVICTION_ALERT_DELIVERY", "dry_run")
    path = tmp_path / "wl.json"
    monkeypatch.setattr(watchlist_store, "WATCHLIST_PATH", str(path))
    watchlist_store.save_watchlist([19], str(path))

    alerts = [
        {"message": "keep", "subnet_id": 19, "dedupe_key": "a"},
        {"message": "drop", "subnet_id": 3, "dedupe_key": "b"},
    ]
    out = deliv.deliver_alerts(alerts)
    assert out["mode"] == "dry_run"
    assert out["delivered"] == 1
    assert out["skipped_watchlist"] == 1
    assert out["dry_run"][0]["subnet_id"] == 19


def test_empty_watchlist_delivers_all_in_dry_run(monkeypatch, tmp_path):
    monkeypatch.setenv("CONVICTION_ALERT_DELIVERY", "dry_run")
    path = tmp_path / "wl.json"
    monkeypatch.setattr(watchlist_store, "WATCHLIST_PATH", str(path))
    path.write_text(json.dumps({"netuids": []}))

    out = deliv.deliver_alerts(
        [
            {"message": "a", "subnet_id": 1, "dedupe_key": "a"},
            {"message": "b", "subnet_id": 2, "dedupe_key": "b"},
        ]
    )
    assert out["delivered"] == 2
    assert out["skipped_watchlist"] == 0
