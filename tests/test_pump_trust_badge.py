"""Pump stale-signal trust badge on /pump — visible only when placeholder snapshots detected."""
from __future__ import annotations

from jinja2 import Environment, FileSystemLoader, select_autoescape


def _render(pump_alerts):
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
    tmpl = env.get_template("pump.html")
    return tmpl.render(pump_alerts=pump_alerts, static_v="test")


def test_trust_badge_shown_when_signal_snapshots_stale():
    html = _render(
        {
            "status": "ok",
            "count": 1,
            "trust": {"ready": False, "signal_snapshots_stale": True},
        }
    )
    assert "pump-trust-badge" in html
    assert "Placeholder signal data" in html


def test_trust_badge_absent_when_trust_ready():
    html = _render({"status": "ok", "count": 0, "trust": {"ready": True}})
    assert "pump-trust-badge" not in html


def test_trust_badge_absent_without_alerts_context():
    html = _render({})
    assert "pump-trust-badge" not in html
