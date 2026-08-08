"""PP-2 — pump pattern surfaces on desk + council predictions."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from internal.learning.prediction_loop import _pattern_at_prediction
from internal.pump.pattern_ledger import classify_waveform, format_direction_strip
from server import app

client = TestClient(app)


def test_pump_desk_template_has_pattern_chip():
    html = Path("templates/partials/premium/pump_alert.html").read_text(encoding="utf-8")
    assert "pump-pattern-line" in html
    assert "pattern_highlight" in html


def test_pump_desk_row_template_has_pattern_chip():
    html = Path("templates/partials/premium/pump_desk_row.html").read_text(encoding="utf-8")
    assert "pump_pattern_line.html" in html
    partial = Path("templates/partials/premium/pump_pattern_line.html").read_text(encoding="utf-8")
    assert "pump-pattern-line" in partial


def test_hydrate_js_renders_pattern_chip():
    body = Path("static/js/cockpit_hydrate.js").read_text(encoding="utf-8")
    assert "pumpPatternLineHtml" in body
    assert "pump-pattern-line" in body
    assert "pattern_highlight" in body
    assert "pds-ladder__dir pump-pattern-chip" not in body


def test_api_pump_patterns_has_class_fields():
    res = client.get("/api/pump-patterns/15")
    assert res.status_code == 200
    body = res.json()
    assert "pattern_class" in body
    assert "pattern_label" in body


def test_pattern_stamp_helper_returns_none_without_data():
    assert _pattern_at_prediction(99999) is None


def test_build_desk_row_includes_pattern_keys():
    from internal.learning.pump_alert import build_desk_row

    row = build_desk_row({"netuid": 15, "phase": "STIRRING", "composite_score": 0.5})
    assert "pattern_class" in row
    assert "pattern_label" in row
    assert "direction_strip" in row
    assert "pattern_confidence" in row
    assert "re_pump_prob" in row


def test_classify_user_example_waveform():
    segments = [
        {"direction": "up", "duration_min": 120, "magnitude_pct": 4.0},
        {"direction": "down", "duration_min": 60, "magnitude_pct": -2.0},
        {"direction": "up", "duration_min": 45, "magnitude_pct": 2.5},
    ]
    match = classify_waveform(segments)
    assert match["pattern_class"] == "PUMP_DROP_RE_PUMP"


def test_format_direction_strip_single_leg():
    segments = [
        {"direction": "up", "duration_min": 11.2, "magnitude_pct": 2.4},
    ]
    strip = format_direction_strip(segments)
    assert strip.startswith("↑")
    assert "+2.4%" in strip
    assert "11m" in strip


def test_format_direction_strip_full_path():
    segments = [
        {"direction": "up", "duration_min": 120, "magnitude_pct": 4.0},
        {"direction": "down", "duration_min": 60, "magnitude_pct": -2.0},
        {"direction": "up", "duration_min": 45, "magnitude_pct": 2.5, "end": "2026-08-06T12:00:00Z"},
    ]
    strip = format_direction_strip(segments, live_last=True)
    assert "↑ +4.0% (2h)" in strip
    assert "↓ -2.0% (1h)" in strip
    assert "↑ +2.5%" in strip and "*" in strip.split("→")[-1]
    assert strip.count("→") == 2
