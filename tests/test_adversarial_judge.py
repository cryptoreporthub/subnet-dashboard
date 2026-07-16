"""Adversarial judge verdicts for jury bridges."""

from internal.council.judge.adversarial import AdversarialJudge


def test_judge_decision_validated():
    judge = AdversarialJudge(persist=False)
    out = judge.judge_decision(
        {"recommended_action": "accumulate", "consensus_score": 0.72},
        {"emission": 1.5, "is_overvalued": False},
    )
    assert out["outcome_label"] == "validated"
    assert out["confidence"] > 0.7


def test_judge_decision_contradicted_when_overvalued():
    judge = AdversarialJudge(persist=False)
    out = judge.judge_decision(
        {"recommended_action": "accumulate", "consensus_score": 0.6},
        {"emission": 0.5, "is_overvalued": True},
    )
    assert out["outcome_label"] == "contradicted"
