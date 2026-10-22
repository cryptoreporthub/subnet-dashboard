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


def test_probe_feed_layers_partial_cache_keeps_blockmachine_with_flag(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_cache(
        tmp_path,
        monkeypatch,
        {
            "synced_at": now,
            "count": 10,
            "live_row_count": 3,
            "refresh_complete": False,
            "subnets": [{"netuid": 1, "live": True, "price": 1.0}],
        },
    )
    layers = probe_feed_layers()
    assert layers["live_cache"]["refresh_complete"] is False
    assert layers["effective_source"] == "blockmachine"
    assert layers.get("live_cache_partial_refresh") is True


def test_sentinel_partial_cache_still_blockmachine_with_live_rows(tmp_path, monkeypatch):
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
    assert info.get("effective_source") == "blockmachine"
    assert info.get("refresh_complete") is False
    assert info.get("live_row_count") == 1


def test_merge_finney_row_keeps_blockmachine_source_for_display_name(monkeypatch):
    from internal.live_subnets import _merge_into_registry
    from internal.subnet_names import display_name_for_netuid

    monkeypatch.setattr("internal.subnet_names._load_name_overrides", lambda: {})
    monkeypatch.setattr(
        "internal.subnet_names.resolve_subnet_name",
        lambda n, **kwargs: "CanonName",
    )
    monkeypatch.setattr(
        "internal.subnet_names.enrich_subnet_row",
        lambda row, **kwargs: dict(row),
    )
    monkeypatch.setattr(
        "internal.live_subnets._registry_list",
        lambda: [{"netuid": 1, "name": "LiveFeedName"}],
    )
    merged = _merge_into_registry(
        [{"netuid": 1, "name": "LiveFeedName", "source": "finney", "price": 1.0}],
    )
    row = next(r for r in merged if r.get("netuid") == 1)
    assert row.get("source") == "blockmachine"
    assert row.get("rpc_provider") == "finney"
    name = display_name_for_netuid(1, subnet_row=row, use_taostats_fallback=False)
    assert name == "LiveFeedName"
    mislabeled = dict(row)
    mislabeled["source"] = "finney"
    mislabeled.pop("rpc_provider", None)
    assert display_name_for_netuid(1, subnet_row=mislabeled, use_taostats_fallback=False) == "CanonName"


def test_merge_chain_only_netuid_is_live_for_market_desk(tmp_path, monkeypatch):
    from internal.live_subnets import _merge_into_registry

    monkeypatch.setattr(
        "internal.live_subnets._registry_list",
        lambda: [{"netuid": 1, "name": "A"}],
    )
    merged = _merge_into_registry([{"netuid": 99, "price": 2.0}])
    row99 = next(r for r in merged if r.get("netuid") == 99)
    assert row99.get("live") is True
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_cache(
        tmp_path,
        monkeypatch,
        {
            "synced_at": now,
            "count": 2,
            "live_row_count": 1,
            "refresh_complete": True,
            "subnets": merged,
        },
    )
    assert _read_live_cache(99).get("subnet", {}).get("netuid") == 99


def test_explicit_zero_live_rows_not_blockmachine(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_cache(
        tmp_path,
        monkeypatch,
        {
            "synced_at": now,
            "count": 10,
            "live_row_count": 0,
            "refresh_complete": True,
            "subnets": [{"netuid": 1, "live": False}],
        },
    )
    layers = probe_feed_layers()
    assert layers["live_cache"]["live_row_count"] == 0
    assert layers["effective_source"] != "blockmachine"
    info = _live_cache_freshness()
    assert info.get("effective_source") is None
    assert info.get("live_row_count") == 0


def test_legacy_cache_all_live_false_not_blockmachine(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_cache(
        tmp_path,
        monkeypatch,
        {
            "synced_at": now,
            "count": 4,
            "subnets": [
                {"netuid": 1, "live": False},
                {"netuid": 2, "live": False},
                {"netuid": 3, "live": False},
                {"netuid": 4, "live": False},
            ],
        },
    )
    layers = probe_feed_layers()
    assert layers["live_cache"]["live_row_count"] == 0
    assert layers["effective_source"] != "blockmachine"
    assert _live_cache_freshness().get("effective_source") is None


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
