"""Expert display — signal-first cause chain and learning attribution."""

from internal.council.expert_display import (
    dominant_expert_for_learning,
    leading_expert_for_pick,
)
from internal.learning.story_path import build_story_path


def test_oro_like_pick_shows_technical_not_quant():
    pick = {
        "expert_contributions": {
            "quant": 1.0,
            "hype": 0.95,
            "technical": 0.75,
            "dark_horse": 0.66,
            "active_signals": [
                "rsi_crossover",
                "macd_cross",
                "stochastic_reversal",
            ],
        }
    }
    leader, label, _score = leading_expert_for_pick(pick)
    assert leader == "technical"
    assert label == "Technical"
    assert dominant_expert_for_learning(pick) == "technical"


def test_story_path_judge_step_matches_fired_signals():
    payload = {
        "action": "HOLD",
        "candidate": {
            "subnet": {"netuid": 15, "name": "ORO"},
            "expert_contributions": {
                "quant": 1.0,
                "technical": 0.75,
                "active_signals": ["rsi_crossover", "macd_cross"],
            },
            "signal_impact": {"active_signals": ["rsi_crossover", "macd_cross"]},
        },
    }
    out = build_story_path(payload)
    judge = next(s for s in out["steps"] if s["id"] == "judges")
    assert "Technical" in judge["title"]
    assert "Quant" not in judge["title"]


def test_delegation_flow_pick_shows_dark_horse():
    pick = {
        "expert_contributions": {
            "quant": 0.7,
            "dark_horse": 0.8,
            "active_signals": ["delegation_flow"],
        }
    }
    assert leading_expert_for_pick(pick)[0] == "dark_horse"
