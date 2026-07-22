"""Tests for canonical subnet name resolution."""

from unittest.mock import patch

from internal.subnet_names import enrich_subnet_row, resolve_subnet_name


def test_resolve_prefers_remote_over_tmc():
    remote = {"40": {"name": "Chunking"}}
    local = {"40": {"id": 40, "name": "Chunking"}}
    name = resolve_subnet_name(
        40,
        local=local,
        remote=remote,
        tmc_name="Ralph",
        use_taostats=False,
    )
    assert name == "Chunking"


def test_sn40_not_ralph():
    """SN40 must not display TaoMarketCap's stale 'Ralph' label."""
    name = resolve_subnet_name(40, tmc_name="Ralph", use_taostats=False)
    assert name != "Ralph"
    assert name == "Chunking" or name == "SN40"


def test_refresh_stored_names():
    from internal.subnet_names import refresh_stored_names

    rows = refresh_stored_names([{"netuid": 40, "name": "Ralph"}])
    assert rows[0]["name"] != "Ralph"


def test_refresh_daily_pick_names():
    from internal.subnet_names import refresh_daily_pick_names

    payload = {
        "pick": {
            "subnet": {"netuid": 40, "name": "Ralph"},
            "final_confidence": 0.7,
        }
    }
    out = refresh_daily_pick_names(payload)
    assert out["pick"]["subnet"]["name"] != "Ralph"


def test_refresh_daily_pick_names_candidate():
    from internal.subnet_names import refresh_daily_pick_names

    payload = {
        "candidate": {
            "subnet": {"netuid": 40, "name": "Ralph"},
            "final_confidence": 0.28,
        },
        "horizon_views": {
            "views": {
                "24h": {"subnet": {"netuid": 40, "name": "Ralph"}, "conviction": 28},
            }
        },
    }
    out = refresh_daily_pick_names(payload)
    assert out["candidate"]["subnet"]["name"] != "Ralph"
    assert out["horizon_views"]["views"]["24h"]["subnet"]["name"] != "Ralph"


def test_dpick_shortlist_uses_canonical_names():
    from internal.learning.dpick_shortlist import build_deliberation_shortlist

    subnets = [
        {"netuid": 40, "name": "Ralph", "emission": 100},
        {"netuid": 41, "name": "Stale", "emission": 90},
    ]
    daily = {"pick": {"subnet": {"netuid": 40, "name": "Ralph"}, "final_confidence": 0.8, "audit": {}}}
    out = build_deliberation_shortlist(subnets, {}, daily)
    assert out["picked"]["name"] != "Ralph"
    if out["alternatives"]:
        assert out["alternatives"][0]["name"] != "Stale" or out["alternatives"][0]["netuid"] != 41


def test_sn28_override_beats_on_chain_lol():
    """SN28 on-chain/taostat identity is 'LOL'; display as gm."""
    remote = {"28": {"name": "LOL", "bittensor_id": "dalet"}}
    name = resolve_subnet_name(28, remote=remote, local={"28": {"name": "LOL"}}, tmc_name="LOL", use_taostats=False)
    assert name == "gm"


def test_pump_alert_resolves_sn28_not_lol():
    from internal.learning.pump_alert import build_alert_row

    row = build_alert_row(
        {"netuid": 28, "name": "LOL", "phase": "PUMPING", "composite_score": 0.75},
        {"netuid": 28, "name": "LOL", "market_cap": 60000, "price": 0.015},
    )
    assert row["name"] == "gm"
    assert "LOL" not in row["move"]


def test_resolve_bad_name_falls_back_to_sn():
    name = resolve_subnet_name(63, local={"63": {"name": "Unknown"}}, remote={}, use_taostats=False)
    assert name == "SN63"


def test_enrich_subnet_row_sets_netuid():
    row = enrich_subnet_row({"id": 8, "name": "deprecated"}, use_taostats=False)
    assert row["netuid"] == 8
    assert row["name"] == "SN8" or row["name"] != "deprecated"


def test_registry_and_subnets_names_agree():
    from fastapi.testclient import TestClient
    from server import app

    client = TestClient(app)
    reg = client.get("/api/registry").json()
    sub = client.get("/api/subnets").json()
    subnets = sub.get("subnets") or []
    by_netuid = {int(s.get("netuid", s.get("id"))): s.get("name") for s in subnets}
    for key, item in reg.items():
        nuid = int(item.get("netuid", item.get("id", key)))
        if nuid in by_netuid:
            assert by_netuid[nuid] == item.get("name"), f"SN{nuid} name mismatch"


def test_mindmap_trail_refreshes_stored_names():
    from internal.learning.mindmap_aggregator import _refresh_trail_names

    rows = _refresh_trail_names([{"netuid": 40, "subnet": "Ralph", "event_type": "signal_triggered"}])
    assert rows[0]["subnet"] != "Ralph"
