"""Frontend audit guards: ice cascade, driver tour order, theme-color."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_proof_ice_selector_beats_legacy_load_order():
    ui = (ROOT / "static/css/ui.css").read_text(encoding="utf-8")
    legacy = (ROOT / "static/css/ui-legacy.css").read_text(encoding="utf-8")
    assert ".proof-band__pct.proof-band__pct--ice" in ui
    assert ".proof-band__pct { font-size: 2.5rem; font-weight: 700; color: #a5f3fc;" in legacy
    assert ".proof-band__pct { font-size: 2.5rem; font-weight: 700; color: #39ff14;" not in legacy


def test_driver_cdn_css_loads_before_ui_legacy():
    base = (ROOT / "templates/base.html").read_text(encoding="utf-8")
    assert base.index("driver.js@1.3.1/dist/driver.css") < base.index("/static/css/ui-legacy.css")


def test_theme_color_aligned_to_mist():
    share = (ROOT / "templates/share/base_share.html").read_text(encoding="utf-8")
    bailout = (ROOT / "internal/instant_bailout.py").read_text(encoding="utf-8")
    base = (ROOT / "templates/base.html").read_text(encoding="utf-8")
    assert 'theme-color" content="#080a10"' in share
    assert 'theme-color" content="#080a10"' in bailout
    assert 'theme-color" content="#080a10"' in base
