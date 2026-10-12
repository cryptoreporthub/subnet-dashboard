"""Coverage honesty propagation for live_subnets cache readers (#1363)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from internal.bots.market_desk import _read_live_cache
from internal.bots.sentinel import _live_cache_freshness
from internal.subnets.feed import probe_feed_layers


def _write_cache(tmp_path, monkeypatch, payload: dict) -> None:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    path = tmp_path / "live_subnets.json"
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_probe_feed_layers_partial_cache_does_not_claim_blockmachine(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_cache(
        tmp_path,
        monkeypatch,
        {
            "synced_at": now,
            "count": 10,
            "live_row_count": 1,
            "refresh_complete": False,
            "subnets": [{"netuid": 1, "live": True, "price": 1.0}],
        },
    )
    layers = probe_feed_layers()
    assert layers["live_cache"]["refresh_complete"] is False
    assert layers["effective_source"] != "blockmachine"


def test_sentinel_partial_cache_no_blockmachine_source(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_cache(
        tmp_path,
        monkeypatch,
        {
            "synced_at": now,
            "count": 5,
            "live_row_count": 1,
            "refresh_complete": False,
            "subnets": [],
        },
    )
    info = _live_cache_freshness()
    assert info.get("effective_source") is None
    assert info.get("refresh_complete") is False


def test_market_desk_skips_registry_only_row(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_cache(
        tmp_path,
        monkeypatch,
        {
            "synced_at": now,
            "count": 2,
            "live_row_count": 1,
            "refresh_complete": True,
            "subnets": [
                {"netuid": 1, "live": True, "price": 1.0},
                {"netuid": 2, "live": False, "name": "registry-only"},
            ],
        },
    )
    live = _read_live_cache(2)
    assert live.get("subnet") is None
    live_ok = _read_live_cache(1)
    assert live_ok.get("subnet", {}).get("live") is True
