"""Tests for canonical subnet name resolution."""

from unittest.mock import patch

from internal.subnet_names import enrich_subnet_row, resolve_subnet_name


def isolate_name_sources(monkeypatch, *, overrides=None, tmc=None, local=None, remote=None):
    monkeypatch.setattr("internal.subnet_names._load_name_overrides", lambda: overrides or {})
    monkeypatch.setattr("internal.subnet_names._tmc_display_names", lambda: tmc or {})
    monkeypatch.setattr("internal.subnet_names._load_local_registry", lambda: local or {})
    monkeypatch.setattr("internal.subnet_names._remote_registry", lambda: remote or {})


def test_resolve_prefers_tmc_over_stale_remote(monkeypatch):
    """TMC is live authority; GitHub taostat JSON can lag rebrands (e.g. SN6)."""
    remote = {"6": {"name": "Infinite Games"}}
    local = {"6": {"name": "Infinite Games"}}
    isolate_name_sources(monkeypatch, tmc={6: "Numinous"}, local=local, remote=remote)
    name = resolve_subnet_name(6, local=local, remote=remote, use_taostats=False)
    assert name == "Numinous"


def test_sn40_override_beats_stale_tmc_ralph(monkeypatch):
    """SN40 override (ralph) beats TaoMarketCap's stale 'Ralph' label."""
    isolate_name_sources(monkeypatch, overrides={"40": "ralph"})
    name = resolve_subnet_name(40, tmc_name="Ralph", use_taostats=False)
    assert name == "ralph"


def test_sn40_not_ralph(monkeypatch):
    """SN40 must not display the naive stored 'Chunking'/TMC label — override wins."""
    isolate_name_sources(monkeypatch, overrides={"40": "ralph"})
    name = resolve_subnet_name(40, tmc_name="Ralph", use_taostats=False)
    assert name != "Ralph"
    assert name == "ralph"


def test_refresh_stored_names(monkeypatch):
    from internal.subnet_names import refresh_stored_names

    isolate_name_sources(monkeypatch, overrides={"40": "ralph"})
    rows = refresh_stored_names([{"netuid": 40, "name": "Ralph"}])
    assert rows[0]["name"] != "Ralph"


def test_refresh_daily_pick_names(monkeypatch):
    from internal.subnet_names import refresh_daily_pick_names

    isolate_name_sources(monkeypatch, overrides={"40": "ralph"})
    payload = {
        "pick": {
            "subnet": {"netuid": 40, "name": "Ralph"},
            "final_confidence": 0.7,
        }
    }
    out = refresh_daily_pick_names(payload)
    assert out["pick"]["subnet"]["name"] != "Ralph"


def test_refresh_daily_pick_names_candidate(monkeypatch):
    from internal.subnet_names import refresh_daily_pick_names

    isolate_name_sources(monkeypatch, overrides={"40": "ralph"})
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


def test_dpick_shortlist_uses_canonical_names(monkeypatch):
    from internal.learning.dpick_shortlist import build_deliberation_shortlist

    isolate_name_sources(monkeypatch)
    subnets = [
        {"netuid": 40, "name": "Ralph", "emission": 100},
        {"netuid": 41, "name": "Stale", "emission": 90},
    ]
    daily = {"pick": {"subnet": {"netuid": 40, "name": "Ralph"}, "final_confidence": 0.8, "audit": {}}}
    out = build_deliberation_shortlist(subnets, {}, daily)
    assert out["picked"]["name"] != "Ralph"
    if out["alternatives"]:
        assert out["alternatives"][0]["name"] != "Stale" or out["alternatives"][0]["netuid"] != 41


def test_sn28_tmc_beats_on_chain_lol():
    """SN28 on-chain/taostat identity is 'LOL'; TMC lists gm."""
    remote = {"28": {"name": "LOL", "bittensor_id": "dalet"}}
    with patch("internal.subnet_names._tmc_display_names", return_value={28: "gm"}):
        with patch("internal.subnet_names._load_name_overrides", return_value={}):
            name = resolve_subnet_name(28, remote=remote, local={"28": {"name": "LOL"}}, use_taostats=False)
    assert name == "gm"


def test_sn15_tmc_beats_stale_remote_de_val():
    """SN15 is ORO on TMC; taostat GitHub still lists De-Val."""
    remote = {"15": {"name": "De-Val", "bittensor_id": "omicron"}}
    with patch("internal.subnet_names._tmc_display_names", return_value={15: "ORO"}):
        with patch("internal.subnet_names._load_name_overrides", return_value={}):
            name = resolve_subnet_name(15, remote=remote, local={"15": {"name": "De-Val"}}, use_taostats=False)
    assert name == "ORO"


def test_pump_alert_resolves_sn28_not_lol(monkeypatch):
    from internal.learning.pump_alert import build_alert_row

    monkeypatch.setattr(
        "internal.subnet_names._tmc_display_names",
        lambda: {28: "gm"},
    )
    monkeypatch.setattr("internal.subnet_names._load_name_overrides", lambda: {})
    monkeypatch.setattr("internal.subnet_names._load_local_registry", lambda: {})
    monkeypatch.setattr("internal.subnet_names._remote_registry", lambda: {})
    row = build_alert_row(
        {"netuid": 28, "name": "LOL", "phase": "PUMPING", "composite_score": 0.75},
        {"netuid": 28, "name": "LOL", "market_cap": 60000, "price": 0.015},
    )
    assert row["name"] == "gm"
    assert "LOL" not in row["move"]


def test_resolve_bad_name_falls_back_to_sn():
    with patch("internal.subnet_names._tmc_display_names", return_value={}):
        with patch("internal.subnet_names._load_name_overrides", return_value={}):
            name = resolve_subnet_name(63, local={"63": {"name": "Unknown"}}, remote={}, use_taostats=False)
    assert name == "SN63"


def test_tmc_display_names_uses_tao_table_not_live_feed():
    """Name cache must use TaoMarketCap table, not blockmachine live feed names."""
    with patch("fetchers.taomarketcap._get_all_subnets_tao", return_value=[{"netuid": 6, "name": "Numinous"}]):
        with patch("fetchers.taomarketcap.get_all_subnets", return_value=[{"netuid": 6, "name": "Infinite Games"}]):
            from internal.subnet_names import _tmc_display_names

            # bust module cache
            import internal.subnet_names as sn

            sn._tmc_name_cache["at"] = 0.0
            assert _tmc_display_names().get(6) == "Numinous"


def test_tmc_cache_beats_stale_row_hint():
    """Blockmachine rows can carry stale names; TMC cache must win."""
    with patch("internal.subnet_names._tmc_display_names", return_value={6: "Numinous"}):
        with patch("internal.subnet_names._load_name_overrides", return_value={}):
            row = enrich_subnet_row(
                {"netuid": 6, "name": "Infinite Games", "source": "blockmachine"},
                use_taostats=False,
            )
    assert row["name"] == "Numinous"


def test_enrich_subnet_row_sets_netuid(monkeypatch):
    isolate_name_sources(monkeypatch)
    row = enrich_subnet_row({"id": 8, "name": "deprecated"}, use_taostats=False)
    assert row["netuid"] == 8
    assert row["name"] == "SN8" or row["name"] != "deprecated"


def test_enrich_subnet_row_skips_taostats_by_default():
    with patch("fetchers.taostats_client.get_subnet_identity") as identity:
        with patch("internal.subnet_names._load_name_overrides", return_value={}):
            with patch("internal.subnet_names._tmc_display_names", return_value={}):
                with patch("internal.subnet_names._load_local_registry", return_value={}):
                    with patch("internal.subnet_names._remote_registry", return_value={}):
                        row = enrich_subnet_row({"netuid": 99, "name": "SN99"})
    identity.assert_not_called()
    assert row["name"] == "SN99"


def test_registry_and_subnets_names_agree(monkeypatch):
    from types import SimpleNamespace

    import server
    from fastapi.testclient import TestClient
    from server import app

    isolate_name_sources(monkeypatch, tmc={42: "CADmind"})
    snapshot = SimpleNamespace(
        rows=[{"netuid": 42, "name": "Live fallback", "source": "blockmachine"}],
        status="live",
        degraded=False,
    )
    monkeypatch.setattr("internal.subnet_universe.ensure_background_refresh", lambda: None)
    monkeypatch.setattr("internal.subnet_universe.get_snapshot", lambda: snapshot)
    monkeypatch.setattr(
        "internal.subnet_universe.universe_snapshot_feed_meta",
        lambda _snapshot: {"source": "blockmachine"},
    )
    monkeypatch.setattr(server, "_SUBNETS_CACHE", {"at": 0.0, "payload": None})
    monkeypatch.setattr(
        server,
        "load_data",
        lambda path: {"42": {"id": 42, "netuid": 42, "name": "Live fallback"}}
        if path == "config/registry.json"
        else {},
    )
    client = TestClient(app)
    reg = client.get("/api/registry").json()
    sub = client.get("/api/subnets").json()
    subnets = sub.get("subnets") or []
    by_netuid = {int(s.get("netuid", s.get("id"))): s.get("name") for s in subnets}
    assert by_netuid[42] == "CADmind"
    assert reg["42"]["name"] == "CADmind"


def test_mindmap_trail_refreshes_stored_names(monkeypatch):
    from internal.learning.mindmap_aggregator import _refresh_trail_names

    isolate_name_sources(monkeypatch, overrides={"40": "ralph"})
    rows = _refresh_trail_names([{"netuid": 40, "subnet": "Ralph", "event_type": "signal_triggered"}])
    assert rows[0]["subnet"] != "Ralph"
