"""Sitewide cyberpunk palette — green/blue/orange lead, pink sparse."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = (ROOT / "static/css/base.css").read_text(encoding="utf-8")
STAGE = (ROOT / "static/css/council_first.css").read_text(encoding="utf-8")
SR = (ROOT / "static/css/situation_room.css").read_text(encoding="utf-8")


def test_root_palette_matches_pulse_lock():
    assert "--accent-primary: #39ff9e" in BASE
    assert "--accent-blue: #3fc9ff" in BASE
    assert "--accent-orange: #ff9f3f" in BASE
    assert "--accent-magenta: #ff3d9a" in BASE
    # Important chrome is green-led, not pink-led
    assert "--border-important: rgba(57, 255, 158, 0.55)" in BASE
    assert "rgba(255, 43, 214" not in BASE  # old hot magenta


def test_stage_and_situation_room_aligned():
    assert "--stage-accent: #39ff9e" in STAGE
    assert "rgba(57, 255, 158" in STAGE  # atmosphere / accents
    assert "--sr-glow-pos: rgba(57, 255, 158" in SR
    assert "--sr-glow-live: rgba(63, 201, 255" in SR
