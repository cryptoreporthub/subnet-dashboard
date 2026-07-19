"""K3-8 — Pump Alert lane tests."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader, select_autoescape

from internal.learning.dpick_pump import build_pump_chip
from internal.learning.pump_alert import build_alert_row, build_pump_alerts
from server import app


def _ladder_entry(phase: str, netuid: int = 29, score: float = 0.71) -> dict:
    return {
        "netuid": netuid,
        "name": "Coldint",
        "phase": phase,
        "composite_score": score,
        "signal_snapshot": {"buy_ratio": 0.68, "volume_intensity": 0.55},
        "updated_at": "2026-07-19T08:00:00Z",
    }


def test_pumping_row_shape():
    row = build_alert_row(_ladder_entry("PUMPING"))
    assert row["badge"] == "PUMPING"
    assert row["move"].startswith("IN PLAY ·")
    assert "motion" in row["thesis"].lower()
    assert "council scan" not in row["thesis"].lower()
    assert "audit gate" not in row["thesis"].lower()


def test_cooling_row_fading():
    row = build_alert_row(_ladder_entry("COOLING", netuid=14, score=0.4))
    assert row["badge"] == "FADING"
    assert row["move"].startswith("FADING ·")


def test_build_pump_alerts_empty():
    ladder = {"subnets": {"29": _ladder_entry("STIRRING")}}
    with patch("internal.pump.state.load_state", return_value=ladder):
        out = build_pump_alerts([])
    assert out["count"] == 0
    assert out["status"] == "empty"
    assert "dossier chip" in out["empty_message"]


def test_build_pump_alerts_pumping_only_counts_primary():
    ladder = {
        "subnets": {
            "29": _ladder_entry("PUMPING"),
            "14": _ladder_entry("COOLING", netuid=14, score=0.3),
        }
    }
    with patch("internal.pump.state.load_state", return_value=ladder):
        out = build_pump_alerts([])
    assert out["count"] == 1
    assert len(out["alerts"]) == 2
    assert out["alerts"][0]["phase"] == "PUMPING"


def test_pumping_not_on_dossier_chip():
    chip = build_pump_chip(29, None, ladder_entry=_ladder_entry("PUMPING"))
    assert chip["show"] is False


def test_pump_alert_template_renders():
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tmpl = env.get_template("partials/premium/pump_alert.html")
    html = tmpl.render(
        pump_alerts={
            "count": 1,
            "empty_message": "No names in PUMPING right now.",
            "alerts": [build_alert_row(_ladder_entry("PUMPING"))],
        }
    )
    assert "section-pump-alert" in html
    assert "IN PLAY ·" in html
    assert "PUMPING" in html


def test_api_pump_alerts_route():
    ladder = {"subnets": {"29": _ladder_entry("PUMPING")}}
    with patch("internal.pump.state.load_state", return_value=ladder):
        with TestClient(app) as client:
            body = client.get("/api/pump-alerts").json()
    assert body["count"] == 1
    assert body["alerts"][0]["phase"] == "PUMPING"


def test_preview_pump_alert_route():
    with TestClient(app) as client:
        html = client.get("/preview/k3-pump-alert").text
    assert "Pump Alert" in html
    assert "IN PLAY ·" in html
