"""N1 — Oracle judge tuning."""

from internal.judges import oracle_judge


def test_oracle_scores_high_on_aligned_hot_signal():
    out = oracle_judge.evaluate(
        {
            "predicted_pct": 4.0,
            "signal_source": "HOT",
            "magnitude_source": "signal_impact",
        },
        signal_impact={
            "impacts": [{"direction": "bullish", "magnitude_pct": 4.0}],
            "net_predicted_pct": 4.0,
            "dominant": "HOT",
        },
        subnet={
            "price": 10.0,
            "apy": 0.18,
            "emission": 2.0,
            "volume": 1000,
            "price_change_24h": 3.0,
            "price_change_7d": 6.0,
        },
    )
    assert out["score"] >= 0.55
    assert out["confidence"] >= 0.5


def test_oracle_penalizes_yield_trap_bullish():
    high = oracle_judge.evaluate(
        {"predicted_pct": 5.0},
        subnet={
            "price": 1.0,
            "apy": 0.2,
            "emission": 1.0,
            "price_change_24h": 2.0,
            "price_change_7d": 4.0,
        },
    )
    trap = oracle_judge.evaluate(
        {"predicted_pct": 5.0},
        subnet={
            "price": 1.0,
            "apy": 0.2,
            "emission": 1.0,
            "price_change_24h": -1.0,
            "price_change_7d": -8.0,
            "yield_trap": True,
        },
    )
    assert trap["score"] < high["score"]
