"""Echo + Oracle council-path honesty."""

from internal.judges import echo_judge, oracle_judge


def test_echo_council_source_uses_real_agreement():
    impacts = [
        {"direction": "bullish"},
        {"direction": "bullish"},
        {"direction": "bullish"},
        {"direction": "bearish"},
    ]
    out = echo_judge.evaluate(
        {"direction": "up", "signal_source": "council_day_pick", "expert": "hype"},
        signal_impact={"impacts": impacts, "net_direction": "bullish"},
        expert_weights={"hype": 1.2},
    )
    assert out["score"] > 0.6


def test_oracle_council_day_pick_aligned():
    out = oracle_judge.evaluate(
        {"predicted_pct": 3.0, "signal_source": "council_day_pick"},
        signal_impact={"impacts": [{"direction": "bullish", "magnitude_pct": 3.0}]},
        subnet={
            "price": 1.0,
            "apy": 0.2,
            "emission": 1.0,
            "price_change_24h": 2.0,
            "price_change_7d": 4.0,
        },
    )
    assert out["score"] >= 0.5
