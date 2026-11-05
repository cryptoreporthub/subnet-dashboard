"""Pump hero D+C-lite visual slot."""

from __future__ import annotations


def test_pump_scan_template_has_phase_visual():
    from pathlib import Path

    html = Path("templates/partials/premium/pump_alert_scan.html").read_text(encoding="utf-8")
    assert "gw-well" in html or "pump_gravity_well" in html
    js = Path("static/js/cockpit_hydrate.js").read_text(encoding="utf-8")
    assert "renderGravityWell" in js
    assert "pds-hero__visual--" in js


def test_pump_full_desk_template_has_phase_visual():
    from pathlib import Path

    html = Path("templates/partials/premium/pump_alert.html").read_text(encoding="utf-8")
    assert "pump_gravity_well" in html
    assert "pd-lead__visual--" in html


def test_hydrate_has_build_pump_hero_visual():
    from pathlib import Path

    js = Path("static/js/cockpit_hydrate.js").read_text(encoding="utf-8")
    assert "function buildPumpHeroVisual" in js
    assert "function renderGravityWell" in js
    assert "Formation <b>" in js
