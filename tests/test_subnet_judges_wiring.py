"""Dashboard judge wiring — subnet metrics must reach evaluate()."""

from internal.judges.subnet_judges import score_subnet


def _subnet(**overrides):
    base = {
        "netuid": 1,
        "name": "A",
        "price": 10.0,
        "apy": 0.2,
        "emission": 1.0,
        "volume": 50_000.0,
        "price_change_24h": 5.0,
        "price_change_7d": 3.0,
        "social_mentions": 5,
    }
    base.update(overrides)
    return base


def test_pulse_responds_to_volume():
    low = score_subnet(1, _subnet(volume=100.0))
    high = score_subnet(1, _subnet(volume=2_000_000.0))
    assert high["pulse"]["score"] > low["pulse"]["score"]


def test_oracle_responds_to_fundamentals():
    full = _subnet(netuid=2, name="B")
    empty = {"netuid": 2, "name": "B"}
    assert score_subnet(2, full)["oracle"]["score"] >= score_subnet(2, empty)["oracle"]["score"]


def test_echo_scores_vary_across_subnets():
    """Dashboard Echo must not collapse to one score for every subnet."""
    a = score_subnet(1, _subnet(price_change_24h=8.0, price_change_7d=6.0, apy=0.25, volume=500_000))
    b = score_subnet(2, _subnet(price_change_24h=2.0, price_change_7d=-4.0, apy=0.06, volume=500.0))
    c = score_subnet(3, _subnet(price_change_24h=-3.0, price_change_7d=-6.0, apy=0.03, volume=200.0))
    echo_scores = {a["echo"]["score"], b["echo"]["score"], c["echo"]["score"]}
    assert len(echo_scores) >= 2
    assert a["echo"]["signals"]["signal_count"] >= 3


def test_oracle_signals_are_observable_not_hardcoded():
    result = score_subnet(4, _subnet(price_change_24h=-2.0, price_change_7d=5.0))
    signals = result["oracle"]["signals"]
    assert "fundamentals" not in signals
    assert signals["price_align_24h"] is True
    assert signals["price_align_7d"] is False
    assert signals["fundamentals_present"] == 3
    assert signals["impact_count"] >= 4
