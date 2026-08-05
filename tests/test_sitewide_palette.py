"""Sitewide cyberpunk palette — green/blue/orange lead, pink sparse."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "static/css/base.css").read_text(encoding="utf-8")
UI = (ROOT / "static/css/ui.css").read_text(encoding="utf-8")


def test_root_palette_matches_pulse_lock():
    assert "--accent-primary: #1fd47c" in BASE
    assert "--accent-blue: #3fc9ff" in BASE
    assert "--accent-orange: #ff9f3f" in BASE
    assert "--accent-violet: #9d8cff" in BASE
    # Magenta token kept as an alias onto violet (sitewide aurora migration)
    assert "--accent-magenta: var(--accent-violet)" in BASE
    # Important chrome is green-led, not pink-led
    assert "--border-important: rgba(31, 212, 124, 0.55)" in BASE
    assert "rgba(255, 43, 214" not in BASE  # old hot magenta
    assert "#39ff9e" not in BASE  # superseded mint-bright green


def test_stage_palette_in_ui_css():
    assert "--stage-accent: #1fd47c" in UI
    assert "rgba(31, 212, 124" in UI  # atmosphere / accents
    assert "--cockpit-green:" in UI  # P3-3l premium cockpit tokens
