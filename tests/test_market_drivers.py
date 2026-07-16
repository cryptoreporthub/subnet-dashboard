"""Market drivers — yield vs price decomposition + learning-loop stats."""

from internal.analytics.market_drivers import (
    build_subnet_driver_card,
    decompose_returns,
    learned_price_drivers,
    market_driver_tags,
)


def test_apy_is_not_price_change():
    sn = {
        "netuid": 8,
        "apy": 0.28,
        "price_change_7d": -12.0,
        "price_change_24h": -3.0,
    }
    d = decompose_returns(sn)
    assert d["staking_yield_apy"] == 28.0
    assert d["price_change_7d"] == -12.0
    assert d["yield_trap"] is True
    assert d["dominant_driver"] == "yield_trap"
    assert any("yield" in w.lower() for w in d["warnings"])


def test_high_apy_pumped_price_is_not_yield_trap():
    sn = {"netuid": 1, "apy": 30.0, "price_change_7d": 20.0}
    d = decompose_returns(sn)
    assert d["yield_trap"] is False
    assert d["dominant_driver"] == "price_momentum_up"


def test_driver_card_never_conflates_yield_with_price():
    sn = {"netuid": 8, "apy": 25.0, "price_change_7d": -8.0, "volume": 50_000}
    card = build_subnet_driver_card(sn)
    why = " ".join(card["why"]).lower()
    assert "price" in why
    assert "not yield" in why or "staking yield" in why
    assert card["risk"] == "high"
    assert card["grade"] in {"C-", "C", "D", "D+"}


def test_market_driver_tags_for_scenario_memory():
    tags = market_driver_tags({"netuid": 8, "apy": 20.0, "price_change_7d": -5.0})
    assert tags["yield_trap"] is True
    assert tags["return_driver"] == "yield_trap"
    assert tags["price_momentum_7d"] == "down"


def test_learned_price_drivers_honest_empty():
    out = learned_price_drivers()
    assert "disclaimer" in out
    assert "top_price_signals" in out
    assert isinstance(out["graded_predictions"], int)
