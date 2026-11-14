"""Echo is excluded from the judge consensus (2026-10-12 decision), reversibly."""

import pytest

from internal.judges import subnet_judges, weights

LEARNED = {"oracle": 1.3339, "echo": 1.0472, "pulse": 0.8665}


class _Judge:
    def __init__(self, score, confidence=0.5):
        self._r = {"score": score, "confidence": confidence}

    def evaluate(self, *a, **k):
        return dict(self._r)


@pytest.fixture(autouse=True)
def _learned_weights(monkeypatch):
    monkeypatch.setattr(weights, "load_judge_weights", lambda path=None: dict(LEARNED))
    monkeypatch.delenv("JUDGE_CONSENSUS_EXCLUDE", raising=False)


def _score(monkeypatch, oracle, echo, pulse):
    monkeypatch.setattr(subnet_judges, "ORACLE", _Judge(oracle, 0.6))
    monkeypatch.setattr(subnet_judges, "ECHO", _Judge(echo, 0.9))
    monkeypatch.setattr(subnet_judges, "PULSE", _Judge(pulse, 0.4))
    return subnet_judges.score_subnet(1, {"netuid": 1, "name": "A", "price": 1.0, "price_change_24h": 3.0})


def test_echo_has_zero_consensus_weight_and_rest_renormalise():
    w = weights.consensus_judge_weights()
    assert w["echo"] == 0.0
    assert w["oracle"] + w["pulse"] == pytest.approx(1.0)
    assert w["oracle"] / w["pulse"] == pytest.approx(LEARNED["oracle"] / LEARNED["pulse"])


def test_learned_weights_untouched_so_echo_can_earn_its_way_back():
    assert weights.normalized_judge_weights()["echo"] > 0.3


def test_empty_env_restores_three_judge_blend(monkeypatch):
    monkeypatch.setenv("JUDGE_CONSENSUS_EXCLUDE", "")
    assert weights.consensus_judge_weights() == pytest.approx(weights.normalized_judge_weights())


def test_consensus_score_ignores_echo_score(monkeypatch):
    low = _score(monkeypatch, 0.8, 0.05, 0.7)["consensus"]
    high = _score(monkeypatch, 0.8, 0.95, 0.7)["consensus"]
    w = weights.consensus_judge_weights()
    assert low["score"] == high["score"] == pytest.approx(0.8 * w["oracle"] + 0.7 * w["pulse"], abs=1e-4)
    assert low["confidence"] == high["confidence"]


def test_excluded_echo_cannot_veto_or_split_the_verdict(monkeypatch):
    out = _score(monkeypatch, 0.9, 0.1, 0.9)["consensus"]
    assert out["verdict"] == "long"
    assert out["agreement"] == 1.0
    assert out["contested"] is False


def test_echo_is_still_scored_and_reported(monkeypatch):
    out = _score(monkeypatch, 0.8, 0.2, 0.7)
    assert out["echo"]["score"] == 0.2


def test_reenabled_echo_does_veto(monkeypatch):
    monkeypatch.setenv("JUDGE_CONSENSUS_EXCLUDE", "")
    assert _score(monkeypatch, 0.9, 0.1, 0.9)["consensus"]["verdict"] == "neutral"


def test_missing_oracle_still_degrades_consensus(monkeypatch):
    assert _score(monkeypatch, None, 0.5, 0.7)["consensus"]["verdict"] == "unavailable"


def test_missing_echo_no_longer_degrades_consensus(monkeypatch):
    assert _score(monkeypatch, 0.8, None, 0.7)["consensus"]["verdict"] != "unavailable"


def test_weighing_room_copy_names_only_voting_judges(monkeypatch):
    from internal.simivision.weighing_room import _voting_judges

    assert _voting_judges() == "Oracle and Pulse"
    monkeypatch.setenv("JUDGE_CONSENSUS_EXCLUDE", "")
    assert _voting_judges() == "Oracle, Echo, and Pulse"
