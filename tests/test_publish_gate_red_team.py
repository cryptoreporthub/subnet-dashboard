"""Publish gate + red-team alpha tuning + confidence calibration."""

from __future__ import annotations

import json

import pytest

from internal.council import state_vector as sv
from internal.council.confidence_calibration import blended_prior, score_boost
from internal.council.publish_gate import publish_gate_fraction, publish_gate_percent
from internal.council.red_team import audit_daily_pick


@pytest.fixture(autouse=True)
def isolate_predictions(tmp_path, monkeypatch):
    pred_path = str(tmp_path / "predictions.json")
    monkeypatch.setattr("internal.council.resolver.PREDICTIONS_PATH", pred_path)
    with open(pred_path, "w") as f:
        json.dump({"predictions": [], "resolved": []}, f)
    yield pred_path


def test_publish_gate_defaults_to_40(monkeypatch):
    monkeypatch.delenv("DAILY_PICK_PUBLISH_GATE", raising=False)
    assert publish_gate_fraction() == pytest.approx(0.40)
    assert publish_gate_percent() == 40


def test_publish_gate_env_override(monkeypatch):
    monkeypatch.setenv("DAILY_PICK_PUBLISH_GATE", "0.35")
    assert publish_gate_fraction() == pytest.approx(0.35)


def test_blended_prior_does_not_collapse_to_coin_flip():
    # Empirical hit ≈ 0.45 must not become the prior (that forced perpetual HOLD).
    prior = blended_prior(0.45)
    assert prior >= 0.52
    assert prior < sv._COLD_START_PRIOR


def test_hit_rate_history_does_not_cap_below_gate(isolate_predictions):
    """n≥30 graded at ~45% hit must still allow healthy picks past 40% gate."""
    resolved = [{"correct": True} if i % 2 == 0 else {"correct": False} for i in range(40)]
    # Force ~45%: 18/40
    resolved = [{"correct": True}] * 18 + [{"correct": False}] * 22
    with open(isolate_predictions, "w") as f:
        json.dump({"predictions": [], "resolved": resolved}, f)

    sn = {"netuid": 1, "name": "A", "price": 1.0, "volume": 8000}
    indicators = {"history_length": 30}
    experts = {"quant": 0.62, "hype": 0.60, "dark_horse": 0.58, "technical": 0.61}
    raw = sv._compute_confidence(sn, indicators, experts, total_score=86.0)
    assert raw >= 0.45
    sn["confidence"] = raw
    audit = audit_daily_pick(sn, [sn])
    assert audit["adjusted_confidence"] >= publish_gate_fraction()


def test_score_boost_helps_high_score_candidates():
    assert score_boost(50) == 0.0
    assert score_boost(80) == pytest.approx(0.06)
    assert score_boost(100) == pytest.approx(0.12)


def test_red_team_caps_compound_haircut(monkeypatch):
    monkeypatch.setenv("RED_TEAM_MAX_HAIRCUT", "0.12")
    sn = {
        "netuid": 58,
        "name": "Thin",
        "price": 1.0,
        "volume": 113,
        "status": "at-risk",
        "risk_flags": ["pruning-risk"],
        "confidence": 0.50,
    }
    audit = audit_daily_pick(sn, [sn] * 3)
    # Without cap, stacked ×0.97×0.95×0.90×0.98 would cut harder; floor is 12%.
    assert audit["adjusted_confidence"] >= 0.50 * 0.88


def test_red_team_alpha_volume_is_note_not_kill_shot(monkeypatch):
    monkeypatch.setenv("RED_TEAM_MAX_HAIRCUT", "0.12")
    sn = {
        "netuid": 82,
        "name": "Compelle",
        "price": 1.0,
        "volume": 440,
        "confidence": 0.47,
        "status": "active",
    }
    audit = audit_daily_pick(sn, [sn])
    assert audit["adjusted_confidence"] >= 0.45
    assert any("Low liquidity" in c for c in audit["concerns"])


def test_sn58_style_candidate_can_clear_40_gate(isolate_predictions, monkeypatch):
    """Replay of 2026-07-26 HOLD crush: high score + thin + at-risk must not land at 20%."""
    monkeypatch.setenv("RED_TEAM_MAX_HAIRCUT", "0.12")
    monkeypatch.delenv("DAILY_PICK_PUBLISH_GATE", raising=False)
    sn = {
        "netuid": 58,
        "name": "Dippy Speech",
        "price": 1.0,
        "volume": 113,
        "status": "at-risk",
        "risk_flags": ["pruning-risk"],
        "emission": 0.1,
    }
    universe = [sn] + [
        {"netuid": i, "name": f"SN{i}", "emission": 5.0, "price": 1.0, "volume": 10_000}
        for i in range(1, 20)
    ]
    indicators = {"history_length": 30}
    experts = {"quant": 0.70, "hype": 0.65, "dark_horse": 0.60, "technical": 0.68}
    raw = sv._compute_confidence(sn, indicators, experts, total_score=88.0)
    sn["confidence"] = raw
    audit = audit_daily_pick(sn, universe)
    # Old path: 42% → 20%. Calibrated path should stay near/above gate territory.
    assert audit["adjusted_confidence"] >= 0.40
