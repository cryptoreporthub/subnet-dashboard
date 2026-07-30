"""PP-0 — pump waveform segment ledger."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from internal.pump.pattern_ledger import append_ladder_sample, load_ledger, pattern_payload


def _ts(minutes: float) -> datetime:
    return datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def test_three_leg_waveform(tmp_path, monkeypatch):
    path = tmp_path / "pump_pattern_ledger.json"
    monkeypatch.setattr("internal.pump.pattern_ledger.STATE_PATH", str(path))

    # 2h up: 1.00 → 1.04 in 8 steps
    for i in range(9):
        append_ladder_sample(15, price=1.0 + i * 0.005, phase="PUMPING", now=_ts(i * 15), path=str(path))

    # 1h down
    for i in range(5):
        append_ladder_sample(
            15,
            price=1.04 - (i + 1) * 0.008,
            phase="COOLING" if i == 4 else "PUMPING",
            now=_ts(120 + i * 15),
            path=str(path),
        )

    # 45m up
    for i in range(4):
        append_ladder_sample(
            15,
            price=1.0 + i * 0.006,
            phase="PUMPING",
            now=_ts(180 + i * 15),
            path=str(path),
        )

    payload = pattern_payload(15, path=str(path))
    assert payload["waveform"]
    directions = [s.get("direction") for s in payload["segments"]]
    assert "up" in directions
    assert "down" in directions
    assert len(payload["segments"]) >= 2

    data = load_ledger(str(path))
    assert len(data["subnets"]["15"]["segments"]) >= 2


def test_pattern_api_route():
    from fastapi.testclient import TestClient

    from server import app

    client = TestClient(app)
    res = client.get("/api/pump-patterns/15")
    assert res.status_code == 200
    body = res.json()
    assert "waveform" in body
    assert "segments" in body

    active = client.get("/api/pump-patterns/active")
    assert active.status_code == 200
    assert "items" in active.json()
