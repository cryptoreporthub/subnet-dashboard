"""Expert attribution — only real council experts count."""

from internal.council.conviction_bands import expert_agreement
from internal.learning.prediction_loop import _dominant_expert


def test_dominant_expert_ignores_nested_technical_score():
    contrib = {
        "quant": 0.4,
        "hype": 0.5,
        "dark_horse": 0.3,
        "technical": 0.45,
        "technical_score": 0.99,
        "signal_contributions": {"rsi": {"score": 0.8}},
    }
    assert _dominant_expert(contrib) == "hype"


def test_expert_agreement_ignores_nested_technical_score():
    contrib = {
        "quant": 0.5,
        "hype": 0.5,
        "dark_horse": 0.5,
        "technical": 0.5,
        "technical_score": 0.1,
    }
    assert expert_agreement(contrib) == 1.0
