"""K3-8b — predictive lead scanner tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader, select_autoescape

from internal.learning.dpick_pump import build_pump_chip
from internal.learning.pump_alert import (
    _progress_series_from_trail,
    build_alert_row,
    build_desk_row,
    build_pump_alerts,
    build_pump_alerts_desk,
)
from internal.pump.state import transition_subnet
from server import app


@pytest.fixture(autouse=True)
def _no_ladder_refresh():
    with patch("internal.pump.refresh.kick_ladder_fresh"):
        with patch("internal.pump.refresh.ensure_ladder_fresh"):
            yield


def _ladder_entry(phase: str, netuid: int = 29, score: float = 0.71) -> dict:
    return {
        "netuid": netuid,
        "name": "Coldint",
        "phase": phase,
        "composite_score": score,
        "signal_snapshot": {"buy_ratio": 0.68, "volume_intensity": 0.55},
        "updated_at": "2026-07-19T08:00:00Z",
    }


def test_stirring_lead_row_predictive():
    row = build_alert_row(_ladder_entry("STIRRING", score=0.28))
    assert row["badge"] == "WARMING UP"
    assert row["timing"] == "lead"
    assert "warming up" in row["thesis"].lower()
    assert "2%+" in row["thesis"]
    assert "ladder" not in row["thesis"].lower()


def test_owner_chip_from_registry_owner():
    row = build_alert_row(
        _ladder_entry("STIRRING", netuid=1, score=0.28),
        {"netuid": 1, "owner": "5HCFWvRqzSHWRPecN7q8J6c7aKQnrCZTMHstPv39xL1wgDHh"},
    )
    assert row["owner_chip"] == "Owner 5HCF…gDHh"


def test_owner_chip_honest_empty_without_owner():
    row = build_alert_row(_ladder_entry("STIRRING", netuid=999, score=0.28), {"netuid": 999})
    assert row.get("owner_chip") is None


def test_desk_row_owner_chip_from_subnet_row():
    row = build_desk_row(
        _ladder_entry("STIRRING", netuid=2, score=0.35),
        {"netuid": 2, "owner": "5EcYQ3W77ndrmMWdvVQusoFqY8doxfP3U2zrh7xZQiaz7avY"},
    )
    assert row["owner_chip"] == "Owner 5EcY…7avY"


def test_accumulating_lead_row():
    row = build_alert_row(_ladder_entry("ACCUMULATING", score=0.48))
    assert row["badge"] == "BUILDING"
    assert row["timing"] == "lead"
    assert "2%+" in row["thesis"]


def test_pumping_just_started_row():
    row = build_alert_row(_ladder_entry("PUMPING", score=0.66))
    assert row["badge"] == "JUST STARTED"
    assert row["timing"] == "confirmed"
    assert "just confirmed" in row["thesis"].lower()
    assert "size down" in row["thesis"].lower()
    assert "0.66" in row["thesis"] or "Coldint" in row["thesis"]


def test_pumping_row_chase_risk_not_entry():
    row = build_alert_row(_ladder_entry("PUMPING", score=0.81))
    assert row["badge"] == "CHASE RISK"
    assert row["timing"] == "confirmed"
    assert "not early" in row["thesis"].lower()
    assert "do not chase" in row["trigger"].lower() or "not chase" in row["trigger"].lower()
    # Per-card specifics — not identical boilerplate across names.
    assert "0.81" in row["thesis"] or "81" in row["thesis"]
    assert "SN29" in row["thesis"] or "Coldint" in row["thesis"]
    assert "Coldint" in row["trigger"] or "SN29" in row["trigger"]


def test_stale_signal_snapshot_rebuilt_from_subnet_row():
    row = build_alert_row(
        {
            "netuid": 28,
            "name": "LOL",
            "phase": "PUMPING",
            "composite_score": 0.75,
            "signal_snapshot": {"buy_ratio": 0.5, "volume_intensity": 1.0},
        },
        {
            "netuid": 28,
            "name": "LOL",
            "buy_volume_24h": 8000,
            "sell_volume_24h": 2000,
            "volume": 50000,
            "emission": 1.5,
        },
    )
    assert row["name"] == "gm"
    assert row["buy_ratio"] != 0.5 or row["volume_intensity"] != 1.0


def test_chase_risk_copy_unique_per_subnet():
    a = build_alert_row(_ladder_entry("PUMPING", netuid=29, score=0.81))
    b = build_alert_row(_ladder_entry("PUMPING", netuid=54, score=0.88))
    assert a["thesis"] != b["thesis"]
    assert a["trigger"] != b["trigger"]


def test_resolve_name_prefers_live_ladder_over_stale_registry():
    """SN54 live desk label is Yanez MIID; committed registry lagged as WebGenieAI."""
    row = build_alert_row(
        {
            "netuid": 54,
            "name": "Yanez MIID",
            "phase": "PUMPING",
            "composite_score": 0.85,
            "signal_snapshot": {"buy_ratio": 0.7, "volume_intensity": 0.5},
        },
        {"netuid": 54, "name": "WebGenieAI"},
    )
    assert "Yanez MIID" in row["move"]
    assert "WebGenieAI" not in row["move"]


def test_resolve_name_override_when_ladder_blank():
    row = build_alert_row(
        {
            "netuid": 54,
            "name": "Unknown",
            "phase": "PUMPING",
            "composite_score": 0.85,
            "signal_snapshot": {"buy_ratio": 0.7, "volume_intensity": 0.5},
        },
        None,
    )
    assert "Yanez MIID" in row["move"]


def test_cooling_row_exit_watch():
    row = build_alert_row(_ladder_entry("COOLING", netuid=14, score=0.4))
    assert row["badge"] == "FADING"
    assert row["timing"] == "exit"
    assert row["move"].startswith("EXIT WATCH ·")


def test_build_pump_alerts_includes_lead_before_confirmed():
    ladder = {
        "subnets": {
            "29": _ladder_entry("PUMPING"),
            "42": _ladder_entry("ACCUMULATING", netuid=42, score=0.48),
            "14": _ladder_entry("COOLING", netuid=14, score=0.3),
        }
    }
    with patch("internal.pump.state.load_state", return_value=ladder):
        out = build_pump_alerts([])
    assert out["early_count"] == 1
    assert out["confirmed_count"] == 1
    assert out["count"] == 2
    assert out["alerts"][0]["timing"] == "lead"
    assert out["alerts"][1]["timing"] == "confirmed"


def test_accumulating_shows_without_strict_lead_gate():
    """ACCUMULATING already passed classifier — desk should not re-gate on buy_ratio."""
    entry = _ladder_entry("ACCUMULATING", netuid=42, score=0.48)
    entry["signal_snapshot"] = {"buy_ratio": 0.4, "volume_intensity": 0.1}
    ladder = {"subnets": {"42": entry}}
    with patch("internal.pump.state.load_state", return_value=ladder):
        out = build_pump_alerts([])
    assert out["early_count"] == 1
    assert out["alerts"][0]["badge"] == "BUILDING"


def test_stirring_without_lead_signals_excluded():
    entry = _ladder_entry("STIRRING", score=0.25)
    entry["signal_snapshot"] = {"buy_ratio": 0.4, "volume_intensity": 0.1}
    ladder = {"subnets": {"29": entry}}
    with patch("internal.pump.state.load_state", return_value=ladder):
        out = build_pump_alerts([])
    assert out["count"] == 0
    assert out["status"] == "empty"


def test_pumping_not_on_dossier_chip():
    chip = build_pump_chip(29, None, ladder_entry=_ladder_entry("PUMPING"))
    assert chip["show"] is False


def test_resolve_name_from_subnet_row():
    row = build_alert_row(
        {"netuid": 106, "name": "Unknown", "phase": "PUMPING", "composite_score": 0.8},
        {"netuid": 106, "name": "FlameWire"},
    )
    assert "FlameWire" in row["move"]


def test_alert_row_includes_whale_day_chips_key():
    row = build_alert_row(_ladder_entry("ACCUMULATING", netuid=42, score=0.48))
    assert "whale_day_chips" in row
    assert isinstance(row["whale_day_chips"], list)


def test_alert_row_surfaces_day_whale_chip(tmp_path, monkeypatch):
    """Recent ledger fill → Day whale chip on the card."""
    import json
    from datetime import datetime, timezone

    from internal.whales.service import WhaleIntelligenceService

    config = tmp_path / "whales.json"
    data = tmp_path / "intel.json"
    config.write_text(json.dumps({"min_tao_notional": 10.0}))
    data.write_text(json.dumps({"events": [], "profiles": {}, "open_positions": {}, "closed_trades": {}}))
    monkeypatch.setenv("WHALES_CONFIG_PATH", str(config))
    monkeypatch.setenv("WHALES_DATA_PATH", str(data))
    svc = WhaleIntelligenceService(config_path=str(config), data_path=str(data))
    now = datetime.now(timezone.utc).isoformat()
    svc.record_event(
        "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY",
        42,
        "buy",
        250.0,
        timestamp=now,
        total_stake_tao=50_000.0,
        slippage_pct=2.5,
        min_notional=10.0,
    )
    row = build_alert_row(
        _ladder_entry("ACCUMULATING", netuid=42, score=0.48),
        {"netuid": 42, "name": "Coldint", "market_cap": 50_000},
    )
    assert row["whale_day_chips"]
    assert any("Day whale" in c for c in row["whale_day_chips"])


def test_pump_alert_template_renders_lead_scanner():
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tmpl = env.get_template("partials/premium/pump_alert.html")
    html = tmpl.render(
        pump_alerts={
            "count": 2,
            "early_count": 1,
            "confirmed_count": 1,
            "empty_message": "No lead.",
            "alerts": [
                build_alert_row(_ladder_entry("ACCUMULATING", netuid=42, score=0.48)),
                build_alert_row(_ladder_entry("PUMPING", score=0.81)),
            ],
        }
    )
    assert "Pump desk" in html
    assert "Warming" in html or "BUILDING" in html
    assert "BUILDING" in html
    assert "CHASE RISK" in html
    assert "chase risk" in html.lower()


def test_pump_alert_compact_hides_detail_lane():
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tmpl = env.get_template("partials/premium/pump_alert.html")
    html = tmpl.render(
        pump_compact=True,
        pump_alerts={
            "count": 1,
            "early_count": 1,
            "confirmed_count": 0,
            "alerts": [build_alert_row(_ladder_entry("ACCUMULATING", netuid=42, score=0.48))],
        },
    )
    assert 'data-pump-compact="1"' in html
    assert "Tier 3" not in html
    assert 'id="pump-list-panel" hidden' in html or "hidden" in html


def test_pump_alert_compact_renders_hero_card():
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tmpl = env.get_template("partials/premium/pump_alert.html")
    row = build_desk_row(_ladder_entry("ACCUMULATING", netuid=42, score=0.72))
    html = tmpl.render(
        pump_compact=True,
        pump_alerts={
            "count": 1,
            "early_count": 1,
            "confirmed_count": 0,
            "exit_count": 0,
            "hero": row,
            "alerts": [row],
            "trust": {"ready": False, "line": "grading starts"},
        },
    )
    assert "pd-lead" in html
    assert "pd-lead__identity" in html
    assert "pd-lead__meter" in html
    assert "pd-verdict" in html
    assert "pd-evidence" in html
    assert "pd-triad" in html
    assert "pd-phase" in html
    assert "Pump desk" in html
    assert "Formation" in html
    assert "Confirm" in html
    assert "Gap" in html
    assert "Inflow" in html
    assert "Open SN" in html and "dossier" in html
    assert "progress_series" in row
    assert row["progress_series"][-1] == int(round(float(row["score"]) / row["trigger_score"] * 100))
    assert row.get("buy_pct") is not None
    assert row.get("vol_pct") is not None
    assert row.get("thesis")
    assert row["thesis"] in html or "pd-verdict__thesis" in html


def test_pump_alert_compact_surfaces_trust_and_census():
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tmpl = env.get_template("partials/premium/pump_alert.html")
    row = build_desk_row(_ladder_entry("ACCUMULATING", netuid=42, score=0.55))
    html = tmpl.render(
        pump_compact=True,
        pump_alerts={
            "count": 1,
            "early_count": 1,
            "confirmed_count": 2,
            "exit_count": 1,
            "hero": row,
            "alerts": [row],
            "trust": {"ready": True, "headline_pct": 62, "headline_n": 12, "line": ""},
        },
    )
    assert "62%" in html
    assert "pd-proof" in html
    assert "pd-census" in html
    assert "1</b> lead" in html
    assert "2</b> live" in html
    assert "1</b> exit" in html
    assert row.get("thesis")


def test_pump_alert_ladder_rows_use_dense_table_columns():
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tmpl = env.get_template("partials/premium/pump_alert.html")
    hero = build_desk_row(_ladder_entry("ACCUMULATING", netuid=1, score=0.6))
    row2 = build_desk_row(_ladder_entry("ACCUMULATING", netuid=2, score=0.5))
    html = tmpl.render(
        pump_compact=True,
        pump_alerts={
            "count": 2,
            "early_count": 2,
            "confirmed_count": 0,
            "exit_count": 0,
            "hero": hero,
            "alerts": [hero, row2],
            "trust": {"ready": False, "line": "grading starts"},
        },
    )
    assert "pd-board" in html
    assert "pd-r pd-r--warm" in html
    assert "Also warming" in html
    assert "pd-r__why" in html
    assert "pd-r__legs" in html


def test_progress_series_from_trail_uses_real_scores():
    entry = {"score_trail": [0.40, 0.44, 0.48]}
    out = _progress_series_from_trail(entry, 0.48, 0.72)
    assert out == [56, 61, 67]


def test_progress_series_fallback_without_trail():
    out = _progress_series_from_trail({}, 0.48, 0.72)
    assert out == [67, 67]


def test_transition_subnet_appends_score_trail():
    state = {"subnets": {}}
    signals = {
        "netuid": 42,
        "name": "Test",
        "volume_intensity": 0.5,
        "momentum_1h": 0.02,
        "price_change_24h": 0.03,
        "buy_ratio": 0.6,
        "chatter_intensity": 0.1,
    }
    _event, _changed = transition_subnet(state, signals)
    entry = state["subnets"]["42"]
    assert isinstance(entry.get("score_trail"), list)
    assert len(entry["score_trail"]) == 1
    _event2, _changed2 = transition_subnet(state, signals)
    assert len(state["subnets"]["42"]["score_trail"]) == 2


def test_api_pump_alerts_route():
    ladder = {"subnets": {"29": _ladder_entry("PUMPING", score=0.81)}}
    with patch("internal.pump.state.load_state", return_value=ladder):
        with TestClient(app) as client:
            body = client.get("/api/pump-alerts").json()
    assert body["confirmed_count"] == 1
    assert body["alerts"][0]["badge"] == "CHASE RISK"
    assert body.get("desk") is True


def test_build_pump_alerts_desk_includes_hero_and_metrics():
    ladder = {
        "subnets": {
            "42": {
                **_ladder_entry("ACCUMULATING", netuid=42, score=0.48),
                "accum_score": 0.81,
            },
            "29": _ladder_entry("PUMPING", score=0.81),
        }
    }
    with patch("internal.pump.state.load_state", return_value=ladder):
        out = build_pump_alerts_desk([])
    assert out.get("hero")
    hero = out["hero"]
    assert hero["formation_pct"] == 81
    assert hero["progress_series"][-1] == int(round(0.48 / hero["trigger_score"] * 100))
    assert "triad" in hero
    assert "triad_labels" in hero
    assert hero["subtitle"]
    ladder = {"subnets": {"29": _ladder_entry("PUMPING", score=0.81)}}
    with patch("internal.pump.state.load_state", return_value=ladder):
        with patch("internal.pump.refresh.kick_ladder_fresh") as kick:
            out = build_pump_alerts_desk([])
    kick.assert_not_called()
    assert out["confirmed_count"] == 1
    assert out["desk"] is True


def test_build_pump_alerts_desk_builds_quickly():
    import time

    ladder = {
        "subnets": {
            str(i): _ladder_entry("ACCUMULATING", netuid=i, score=0.4 + i * 0.01)
            for i in range(1, 130)
        }
    }
    with patch("internal.pump.state.load_state", return_value=ladder):
        t0 = time.monotonic()
        out = build_pump_alerts_desk([])
        elapsed = time.monotonic() - t0
    assert elapsed < 0.5
    assert out["status"] in ("success", "empty")


def test_api_pump_alerts_timeout_serves_stale_not_cache(monkeypatch):
    import asyncio
    import time

    import server as srv

    good = {
        "status": "success",
        "count": 1,
        "early_count": 0,
        "confirmed_count": 1,
        "alerts": [{"netuid": 29, "badge": "CHASE RISK"}],
        "desk": True,
    }
    monkeypatch.setattr(srv, "_PUMP_ALERTS_TTL", 60.0)
    monkeypatch.setattr(
        srv,
        "_PUMP_ALERTS_CACHE",
        {"at": time.monotonic(), "payload": good},
    )

    async def _always_timeout(fn, timeout_s, *, label):
        raise asyncio.TimeoutError()

    with patch.object(srv, "_to_thread_timeout", side_effect=_always_timeout):
        with TestClient(app) as client:
            body = client.get("/api/pump-alerts").json()
    assert body["status"] == "success"
    assert body["count"] == 1


def test_preview_pump_alert_route():
    with TestClient(app) as client:
        html = client.get("/preview/k3-pump-alert").text
    assert "Pump desk" in html
    assert "BUILDING" in html


def test_pump_alert_scan_compact_renders_hero():
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tmpl = env.get_template("partials/premium/pump_alert_scan.html")
    row = build_desk_row(_ladder_entry("ACCUMULATING", netuid=42, score=0.72))
    html = tmpl.render(
        pump_compact=True,
        pump_alerts={
            "count": 1,
            "early_count": 1,
            "confirmed_count": 0,
            "exit_count": 0,
            "hero": row,
            "alerts": [row],
            "trust": {"ready": False, "line": "grading starts"},
        },
    )
    assert 'data-pump-compact="1"' in html
    assert 'data-pump-scan="1"' in html
    assert "pds-hero" in html
    assert "pds-strip" in html
    assert "pd-evidence" not in html
    assert "pd-verdict__trigger" not in html
    assert "Open SN" in html and "dossier" in html
    assert 'class="pds-variant"' not in html


def test_pump_alert_scan_compact_surfaces_trust_and_census():
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tmpl = env.get_template("partials/premium/pump_alert_scan.html")
    row = build_desk_row(_ladder_entry("ACCUMULATING", netuid=42, score=0.55))
    html = tmpl.render(
        pump_compact=True,
        pump_alerts={
            "count": 1,
            "early_count": 1,
            "confirmed_count": 2,
            "exit_count": 1,
            "hero": row,
            "alerts": [row],
            "trust": {"ready": True, "headline_pct": 62, "headline_n": 12, "line": ""},
        },
    )
    assert "62%" in html
    assert "pds-proof__line" in html
    assert 'id="pd-census-lead">1</span> lead' in html
    assert 'id="pd-census-live">2</span> live' in html
    assert 'id="pd-census-exit">1</span> exit' in html


def test_preview_pump_alert_scan_matches_home_markup():
    with TestClient(app) as client:
        html = client.get("/preview/k3-pump-alert-scan").text
    assert 'id="section-pump-alert"' in html
    assert 'data-pump-compact="1"' in html
    assert "pds-hero" in html
    assert "pds-strip" in html
    assert "pd-evidence" not in html


def test_preview_pump_alert_scan_route():
    with TestClient(app) as client:
        html = client.get("/preview/k3-pump-alert-scan").text
    assert "Pump desk" in html
    assert "pds-hero" in html
    assert "pds-strip" in html
    assert "pds-ladder" in html
    assert "pd-evidence" not in html
    assert "pd-verdict__trigger" not in html


def test_preview_pump_desk_polish_route():
    with TestClient(app) as client:
        html = client.get("/preview/pump-desk-polish").text
    assert "pds--polish" in html
    assert "pds-phase" in html
    assert "pds-proof__pct" in html
    assert "Open full desk" in html
    assert 'href="/preview/pump-desk-full"' in html


def test_preview_pump_desk_full_route():
    with TestClient(app) as client:
        html = client.get("/preview/pump-desk-full").text
    assert "pd-evidence" in html
    assert "pd-phase" in html
    assert "pd-proof__pct" in html
