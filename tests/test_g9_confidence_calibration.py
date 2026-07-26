"""G9 — confidence calibration against resolver history."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from internal.council import state_vector as sv
from internal.council.confidence_calibration import blended_prior


@pytest.fixture(autouse=True)
def isolate_predictions(tmp_path, monkeypatch):
    pred_path = str(tmp_path / "predictions.json")
    monkeypatch.setattr("internal.council.resolver.PREDICTIONS_PATH", pred_path)
    with open(pred_path, "w") as f:
        json.dump({"predictions": [], "resolved": []}, f)
    yield pred_path


def _confidence(sn, indicators, experts, total_score=None):
    return sv._compute_confidence(sn, indicators, experts, total_score=total_score)


def test_cold_start_prior_when_insufficient_history(isolate_predictions):
    sn = {"netuid": 1, "name": "A", "price": 1.0, "volume": 100}
    indicators = {"history_length": 30}
    experts = {"quant": 0.6, "hype": 0.6, "dark_horse": 0.6, "technical": 0.6}
    assert _confidence(sn, indicators, experts) == pytest.approx(
        sv._COLD_START_PRIOR * 1.0 * 1.0, rel=1e-3
    )


def test_resolver_hit_rate_blended_not_raw(isolate_predictions):
    """Enough graded history blends toward hit rate — does not replace prior."""
    resolved = [{"correct": True} if i % 2 == 0 else {"correct": False} for i in range(40)]
    with open(isolate_predictions, "w") as f:
        json.dump({"predictions": [], "resolved": resolved}, f)

    sn = {"netuid": 1, "name": "A", "price": 1.0, "volume": 100}
    indicators = {"history_length": 30}
    experts = {"quant": 0.6, "hype": 0.6, "dark_horse": 0.6, "technical": 0.6}
    hit = 20 / 40
    prior = blended_prior(hit)
    from internal.council.confidence_calibration import reliability_factor

    expected = prior * 1.0 * 1.0 * reliability_factor(hit)
    assert _confidence(sn, indicators, experts) == pytest.approx(expected, rel=1e-3)
    # Must stay well above raw hit rate (the old bug).
    assert _confidence(sn, indicators, experts) > hit + 0.05


def test_completeness_penalizes_missing_fields():
    sn = {"netuid": 1, "name": "", "price": None, "volume": 0}
    indicators = {"history_length": 5}
    experts = {"quant": 0.5, "hype": 0.5, "dark_horse": 0.5, "technical": 0.5}
    conf = _confidence(sn, indicators, experts)
    assert conf < 0.5


def test_agreement_boosts_when_experts_align():
    sn = {"netuid": 1, "name": "A", "price": 1.0, "volume": 100}
    indicators = {"history_length": 30}
    aligned = {"quant": 0.7, "hype": 0.7, "dark_horse": 0.7, "technical": 0.7}
    spread = {"quant": 0.9, "hype": 0.1, "dark_horse": 0.5, "technical": 0.5}
    assert _confidence(sn, indicators, aligned) > _confidence(sn, indicators, spread)


def test_no_bogus_price_change_boost():
    """price_change_24h presence alone must not inflate confidence."""
    base_sn = {"netuid": 1, "name": "A", "price": 1.0, "volume": 100}
    with_chg = {**base_sn, "price_change_24h": 5.0, "price_change_7d": 10.0}
    indicators = {"history_length": 30}
    experts = {"quant": 0.6, "hype": 0.6, "dark_horse": 0.6, "technical": 0.6}
    assert _confidence(base_sn, indicators, experts) == _confidence(with_chg, indicators, experts)


def test_confidence_bounded_zero_to_one(isolate_predictions):
    sn = {"netuid": 1, "name": "A", "price": 1.0, "volume": 100}
    indicators = {"history_length": 30}
    experts = {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}
    conf = _confidence(sn, indicators, experts, total_score=100)
    assert 0.0 <= conf <= 1.0


def test_zero_hit_rate_still_has_floor(isolate_predictions):
    """Even 0% empirical hit rate blends toward cold start — never zeros confidence."""
    resolved = [{"correct": False} for _ in range(30)]
    with open(isolate_predictions, "w") as f:
        json.dump({"predictions": [], "resolved": resolved}, f)

    sn = {"netuid": 1, "name": "A", "price": 1.0, "volume": 100}
    indicators = {"history_length": 30}
    experts = {"quant": 0.6, "hype": 0.6, "dark_horse": 0.6, "technical": 0.6}
    conf = _confidence(sn, indicators, experts)
    assert conf > 0.35
