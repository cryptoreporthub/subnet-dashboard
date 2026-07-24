"""K3-8b — predictive lead scanner tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader, select_autoescape

from internal.learning.dpick_pump import build_pump_chip
from internal.learning.pump_alert import build_alert_row, build_pump_alerts
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


def test_api_pump_alerts_route():
    ladder = {"subnets": {"29": _ladder_entry("PUMPING", score=0.81)}}
    with patch("internal.pump.state.load_state", return_value=ladder):
        with TestClient(app) as client:
            body = client.get("/api/pump-alerts").json()
    assert body["confirmed_count"] == 1
    assert body["alerts"][0]["badge"] == "CHASE RISK"


def test_preview_pump_alert_route():
    with TestClient(app) as client:
        html = client.get("/preview/k3-pump-alert").text
    assert "Pump desk" in html
    assert "BUILDING" in html
