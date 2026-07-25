"""Dashboard judge wiring — subnet metrics must reach evaluate()."""

from internal.judges.subnet_judges import score_subnet


def test_pulse_responds_to_volume():
    low = score_subnet(
        1,
        {
            "netuid": 1,
            "name": "A",
            "price": 10.0,
            "apy": 0.2,
            "emission": 1.0,
            "volume": 100.0,
            "price_change_24h": 5.0,
            "social_mentions": 5,
        },
    )
    high = score_subnet(
        1,
        {
            "netuid": 1,
            "name": "A",
            "price": 10.0,
            "apy": 0.2,
            "emission": 1.0,
            "volume": 2_000_000.0,
            "price_change_24h": 5.0,
            "social_mentions": 5,
        },
    )
    assert high["pulse"]["score"] > low["pulse"]["score"]


def test_oracle_responds_to_fundamentals():
    full = {
        "netuid": 2,
        "name": "B",
        "price": 10.0,
        "apy": 0.3,
        "emission": 2.0,
        "volume": 1000.0,
        "price_change_24h": 2.0,
        "social_mentions": 1,
    }
    empty = {"netuid": 2, "name": "B"}
    assert score_subnet(2, full)["oracle"]["score"] >= score_subnet(2, empty)["oracle"]["score"]
