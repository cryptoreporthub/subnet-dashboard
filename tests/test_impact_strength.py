"""Adjustable impact_strength dial + SimiVision learning nudge."""

import json
import os

from internal.council.weights import (
    load_impact_strength,
    nudge_impact_strength,
    save_impact_strength,
)
from internal.subnets.impact import impact_scale_factor, scale_move_by_impact


def _row(mcap):
    return {
        "netuid": 1,
        "name": "X",
        "market_cap": mcap,
        "volume": 1000,
        "price": 1.0,
    }


def test_impact_strength_zero_flattens_scale(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"adversarial_state": {"impact_strength": 0.0}}))
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    monkeypatch.delenv("IMPACT_STRENGTH", raising=False)
    large = _row(400_000)
    assert abs(impact_scale_factor(large) - 1.0) < 1e-6
    assert scale_move_by_impact(10.0, large) == 10.0


def test_impact_strength_two_more_aggressive_than_one(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    monkeypatch.delenv("IMPACT_STRENGTH", raising=False)
    large = _row(400_000)
    save_impact_strength(1.0, str(soul))
    f1 = impact_scale_factor(large)
    save_impact_strength(2.0, str(soul))
    f2 = impact_scale_factor(large)
    assert f2 < f1 < 1.0  # stronger dial → harder dampen on large caps


def test_env_override_locks_nudge(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"adversarial_state": {"impact_strength": 1.0}}))
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    monkeypatch.setenv("IMPACT_STRENGTH", "0.5")
    assert load_impact_strength(str(soul)) == 0.5
    after = nudge_impact_strength(True, tier="small", path=str(soul))
    assert after == 0.5  # locked


def test_nudge_small_correct_raises_strength(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"adversarial_state": {"impact_strength": 1.0}}))
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    monkeypatch.delenv("IMPACT_STRENGTH", raising=False)
    after = nudge_impact_strength(True, tier="small", path=str(soul))
    assert after == 1.02


def test_nudge_large_correct_lowers_strength(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    soul.write_text(json.dumps({"adversarial_state": {"impact_strength": 1.0}}))
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))
    monkeypatch.delenv("IMPACT_STRENGTH", raising=False)
    after = nudge_impact_strength(True, tier="large", path=str(soul))
    assert after == 0.98


def test_calibration_status_exposes_impact_strength(client=None):
    from fastapi.testclient import TestClient
    from server import app

    resp = TestClient(app).get("/api/calibration/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "impact_strength" in body
    assert body["calibration"]["impact_strength"]["default"] == 1.0
    assert body["calibration"]["impact_strength"]["env_override"] == "IMPACT_STRENGTH"
