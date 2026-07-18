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
