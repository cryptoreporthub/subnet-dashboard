"""Day Lens selects the subnet. Signal-first names the displayed expert."""

from internal.council.expert_display import (
    dominant_expert_for_learning,
    leading_expert_for_pick,
)
from internal.council.state_vector import selection_weights


def test_selection_weights_apply_day_lens_then_normalize():
    raw = {"quant": 0.30, "hype": 0.25, "dark_horse": 0.20, "technical": 0.25}
    scaled = {
        "quant": raw["quant"] * 1.05,
        "hype": raw["hype"] * 0.90,
        "dark_horse": raw["dark_horse"] * 1.08,
        "technical": raw["technical"] * 1.05,
    }
    total = sum(scaled.values())
    got = selection_weights(raw)
    assert got == {name: value / total for name, value in scaled.items()}
    assert abs(sum(got.values()) - 1.0) < 1e-12


def test_signal_first_display_ignores_day_lens_winner():
    weights = {"quant": 0.01, "hype": 0.01, "dark_horse": 0.39, "technical": 0.40}
    scores = {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}
    selected = max(scores, key=lambda name: scores[name] * selection_weights(weights)[name])
    pick = {
        "active_signals": ["momentum_shift"],
        "expert_contributions": scores,
    }
    leader, label, display_score = leading_expert_for_pick(
        pick, market_context={"weights": weights}
    )
    assert selected == "dark_horse"
    assert leader == "hype"
    assert label == "Hype"
    assert display_score == 1.0
    assert dominant_expert_for_learning(pick) == "hype"


def test_fallback_blend_skips_day_lens_and_breaks_ties_by_name():
    weights = {"quant": 0.01, "hype": 0.01, "dark_horse": 0.39, "technical": 0.40}
    scores = {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}
    pick = {"expert_contributions": scores}
    leader, _, _ = leading_expert_for_pick(pick, market_context={"weights": weights})
    selected = max(scores, key=lambda name: scores[name] * selection_weights(weights)[name])
    assert selected == "dark_horse"
    assert leader == "technical"

    tied = {"expert_contributions": scores}
    tie_leader, _, _ = leading_expert_for_pick(
        tied,
        market_context={"weights": {name: 1.0 for name in scores}},
    )
    assert tie_leader == "technical"
