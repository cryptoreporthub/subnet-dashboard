"""Frontend audit guards: ice cascade, driver tour order, theme-color."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_proof_ice_selector_in_ui_css():
    ui = (ROOT / "static/css/ui.css").read_text(encoding="utf-8")
    assert ".proof-band__pct.proof-band__pct--ice" in ui
    assert ".proof-band__pct { font-size: 2.5rem; font-weight: 700; color: #a5f3fc;" in ui


def test_driver_cdn_css_present_without_legacy():
    base = (ROOT / "templates/base.html").read_text(encoding="utf-8")
    assert "driver.js@1.3.1/dist/driver.css" in base
    assert "/static/css/ui.css" in base
    assert "ui-legacy.css" not in base


def test_theme_color_aligned_to_mist():
    share = (ROOT / "templates/share/base_share.html").read_text(encoding="utf-8")
    bailout = (ROOT / "internal/instant_bailout.py").read_text(encoding="utf-8")
    base = (ROOT / "templates/base.html").read_text(encoding="utf-8")
    assert 'theme-color" content="#080a10"' in share
    assert 'theme-color" content="#080a10"' in bailout
    assert 'theme-color" content="#080a10"' in base
