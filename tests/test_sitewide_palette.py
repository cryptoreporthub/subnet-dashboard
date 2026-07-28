"""Sitewide cyberpunk palette — green/blue/orange lead, pink sparse."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "static/css/base.css").read_text(encoding="utf-8")
STAGE = (ROOT / "static/css/council_first.css").read_text(encoding="utf-8")
SR = (ROOT / "static/css/situation_room.css").read_text(encoding="utf-8")


def test_root_palette_matches_pulse_lock():
    assert "--accent-primary: #1fd47c" in BASE
    assert "--accent-blue: #3fc9ff" in BASE
    assert "--accent-orange: #ff9f3f" in BASE
    assert "--accent-magenta: #ff3d9a" in BASE
    # Important chrome is green-led, not pink-led
    assert "--border-important: rgba(31, 212, 124, 0.55)" in BASE
    assert "rgba(255, 43, 214" not in BASE  # old hot magenta
    assert "#39ff9e" not in BASE  # superseded mint-bright green


def test_stage_and_situation_room_aligned():
    assert "--stage-accent: #1fd47c" in STAGE
    assert "rgba(31, 212, 124" in STAGE  # atmosphere / accents
    assert "--sr-glow-pos: rgba(31, 212, 124" in SR
    assert "--sr-glow-live: rgba(63, 201, 255" in SR
