"""PP-1 — pump pattern taxonomy classifier."""

from __future__ import annotations

from internal.pump.pattern_ledger import classify_waveform


def _seg(direction: str, minutes: float, magnitude: float = 1.0) -> dict:
    return {
        "direction": direction,
        "duration_min": minutes,
        "magnitude_pct": magnitude,
    }


def test_insufficient_data():
    match = classify_waveform([_seg("up", 60)])
    assert match["pattern_class"] == "insufficient_data"


def test_pump_drop_re_pump_user_example():
    segments = [
        _seg("up", 120, 4.0),
        _seg("down", 60, -2.0),
        _seg("up", 45, 2.5),
    ]
    match = classify_waveform(segments)
    assert match["pattern_class"] == "PUMP_DROP_RE_PUMP"
    assert "↑" in match["pattern_label"]
    assert match["confidence"] >= 0.8


def test_pump_drop():
    match = classify_waveform([_seg("up", 90, 3.0), _seg("down", 30, -1.5)])
    assert match["pattern_class"] == "PUMP_DROP"


def test_pattern_api_includes_class():
    from fastapi.testclient import TestClient

    from server import app

    client = TestClient(app)
    res = client.get("/api/pump-patterns/15")
    assert res.status_code == 200
    body = res.json()
    assert "pattern_class" in body
    assert "pattern_label" in body
    assert "confidence" in body
