"""Pump hero D+C-lite visual slot."""

from __future__ import annotations


def test_pump_scan_template_has_phase_visual():
    from pathlib import Path

    html = Path("templates/partials/premium/pump_alert_scan.html").read_text(encoding="utf-8")
    assert "pds-hero__visual--" in html
    assert "pds-hero__arc" in html


def test_hydrate_has_build_pump_hero_visual():
    from pathlib import Path

    js = Path("static/js/cockpit_hydrate.js").read_text(encoding="utf-8")
    assert "function buildPumpHeroVisual" in js
    assert "pds-hero__visual--" in js
