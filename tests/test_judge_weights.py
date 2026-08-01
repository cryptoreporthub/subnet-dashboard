"""Tests for per-judge confidence weights (Oracle/Echo/Pulse learning loop)."""

import pytest

from internal.judges.subnet_judges import score_subnet
from internal.judges.weights import (
    DEFAULT_JUDGE_WEIGHTS,
    _LEARNING_MAX_WEIGHT,
    _LEARNING_MIN_WEIGHT,
    load_judge_weights,
    normalized_judge_weights,
    nudge_judge,
)
from internal.store.soul_map_io import read_soul_map, write_soul_map


def test_default_judge_weights_sum_to_one_and_match_hardcoded_mix():
    assert DEFAULT_JUDGE_WEIGHTS == {"oracle": 0.35, "echo": 0.30, "pulse": 0.35}
    assert sum(DEFAULT_JUDGE_WEIGHTS.values()) == 1.0


def test_load_judge_weights_returns_defaults_when_key_missing(tmp_path):
    soul_path = tmp_path / "soul_map.json"
    write_soul_map(lambda blob: blob.update({"unrelated": 1}), path=str(soul_path))
    assert load_judge_weights(path=str(soul_path)) == DEFAULT_JUDGE_WEIGHTS

    missing = tmp_path / "missing.json"
    assert load_judge_weights(path=str(missing)) == DEFAULT_JUDGE_WEIGHTS


def test_nudge_judge_correct_increases_weight_within_bounds(tmp_path):
    soul_path = tmp_path / "soul_map.json"
    prev = load_judge_weights(path=str(soul_path))["oracle"]
    for _ in range(100):
        after = nudge_judge("oracle", True, path=str(soul_path))
        assert after is not None
        assert after >= prev
        assert after <= _LEARNING_MAX_WEIGHT
        prev = after
    assert prev == _LEARNING_MAX_WEIGHT


def test_nudge_judge_wrong_decreases_weight_within_bounds(tmp_path):
    soul_path = tmp_path / "soul_map.json"
    prev = load_judge_weights(path=str(soul_path))["oracle"]
    for _ in range(100):
        after = nudge_judge("oracle", False, path=str(soul_path))
        assert after is not None
        assert after <= prev
        assert after >= _LEARNING_MIN_WEIGHT
        prev = after
    assert prev == _LEARNING_MIN_WEIGHT


def test_nudge_judge_invalid_name_returns_none(tmp_path):
    soul_path = tmp_path / "soul_map.json"
    write_soul_map(lambda blob: blob.update({"seed": True}), path=str(soul_path))
    result = nudge_judge("nonexistent", True, path=str(soul_path))
    assert result is None
    data = read_soul_map(str(soul_path))
    assert "judge_weights" not in data
    assert data.get("seed") is True


def test_nudge_judge_preserves_unrelated_soul_map_keys(tmp_path):
    soul_path = tmp_path / "soul_map.json"
    write_soul_map(
        lambda blob: blob.update({"some_other_key": {"foo": 1}}),
        path=str(soul_path),
    )
    nudge_judge("echo", True, path=str(soul_path))
    data = read_soul_map(str(soul_path))
    assert data.get("some_other_key") == {"foo": 1}
    assert "judge_weights" in data


def test_normalized_judge_weights_sums_to_one(tmp_path):
    soul_path = tmp_path / "soul_map.json"
    nudge_judge("oracle", True, path=str(soul_path))
    nudge_judge("oracle", True, path=str(soul_path))
    nudge_judge("pulse", False, path=str(soul_path))
    normed = normalized_judge_weights(path=str(soul_path))
    assert abs(sum(normed.values()) - 1.0) < 1e-9


@pytest.fixture
def _mock_judge_scores(monkeypatch):
    """Fixed per-judge scores for consensus tests."""
    monkeypatch.setattr(
        "internal.judges.subnet_judges.ORACLE.evaluate",
        lambda *_a, **_k: {"score": 0.8, "confidence": 0.7},
    )
    monkeypatch.setattr(
        "internal.judges.subnet_judges.ECHO.evaluate",
        lambda *_a, **_k: {"score": 0.5, "confidence": 0.6},
    )
    monkeypatch.setattr(
        "internal.judges.subnet_judges.PULSE.evaluate",
        lambda *_a, **_k: {"score": 0.2, "confidence": 0.4},
    )


def test_score_subnet_consensus_unchanged_when_judge_weights_absent(
    monkeypatch, tmp_path, _mock_judge_scores
):
    soul_path = tmp_path / "soul_map.json"
    monkeypatch.setattr("internal.judges.weights.SOUL_MAP_PATH", str(soul_path))

    subnet = {
        "netuid": 10,
        "name": "WeightsAbsent",
        "price": 10.0,
        "apy": 0.5,
        "emission": 100.0,
        "stake": 1000.0,
        "volume": 500000.0,
        "price_change_24h": 5.0,
        "social_mentions": 10,
        "social_sentiment": 0.6,
    }
    result = score_subnet(10, subnet)

    oracle_score, echo_score, pulse_score = 0.8, 0.5, 0.2
    oracle_conf, echo_conf, pulse_conf = 0.7, 0.6, 0.4
    expected_score = (
        oracle_score * 0.35 + echo_score * 0.30 + pulse_score * 0.35
    )
    expected_conf = (
        oracle_conf * 0.35 + echo_conf * 0.30 + pulse_conf * 0.35
    )
    assert result["consensus"]["score"] == pytest.approx(round(expected_score, 4))
    assert result["consensus"]["confidence"] == pytest.approx(round(expected_conf, 4))


def test_score_subnet_consensus_reflects_nudged_weights(
    monkeypatch, tmp_path, _mock_judge_scores
):
    soul_path = tmp_path / "soul_map.json"
    monkeypatch.setattr("internal.judges.weights.SOUL_MAP_PATH", str(soul_path))

    subnet = {
        "netuid": 11,
        "name": "WeightsNudged",
        "price": 10.0,
        "apy": 0.5,
        "emission": 100.0,
        "stake": 1000.0,
        "volume": 500000.0,
        "price_change_24h": 5.0,
        "social_mentions": 10,
        "social_sentiment": 0.6,
    }
    baseline = score_subnet(11, subnet)
    old_consensus = baseline["consensus"]["score"]
    oracle_score = 0.8

    for _ in range(20):
        nudge_judge("oracle", True, path=str(soul_path))
    for _ in range(20):
        nudge_judge("pulse", False, path=str(soul_path))

    nudged = score_subnet(11, subnet)
    new_consensus = nudged["consensus"]["score"]

    assert abs(new_consensus - oracle_score) < abs(old_consensus - oracle_score)
    assert new_consensus > old_consensus


def test_tracker_on_prediction_resolved_nudges_all_three_judges_independently(
    monkeypatch, tmp_path
):
    from internal.judges import judges as judges_mod
    from internal.judges.tracker import on_prediction_resolved

    soul_path = tmp_path / "soul_map.json"
    monkeypatch.setattr("internal.judges.weights.SOUL_MAP_PATH", str(soul_path))

    before = load_judge_weights(path=str(soul_path))

    def _close_oracle(prediction, actual_pct=None, outcome=None):
        return {"pnl_pct": 5.0}

    def _close_echo(prediction, actual_pct=None, outcome=None):
        return {"pnl_pct": -2.0}

    def _close_pulse(prediction, actual_pct=None, outcome=None):
        return {"pnl_pct": 3.0}

    monkeypatch.setattr(judges_mod.ORACLE, "close_position", _close_oracle)
    monkeypatch.setattr(judges_mod.ECHO, "close_position", _close_echo)
    monkeypatch.setattr(judges_mod.PULSE, "close_position", _close_pulse)
    monkeypatch.setattr(judges_mod.ORACLE, "record_postmortem", lambda *a, **k: None)
    monkeypatch.setattr(judges_mod.ECHO, "record_postmortem", lambda *a, **k: None)
    monkeypatch.setattr(judges_mod.PULSE, "record_postmortem", lambda *a, **k: None)

    prediction = {
        "id": "judge-weight-test",
        "correct": False,
        "outcome": "miss",
        "reference_price": 10.0,
        "resolved_price": 9.0,
    }
    on_prediction_resolved(prediction)

    after = load_judge_weights(path=str(soul_path))
    assert after["oracle"] > before["oracle"]
    assert after["echo"] < before["echo"]
    assert after["pulse"] > before["pulse"]
