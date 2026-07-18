"""Dark Horse score blends crash-tail with on-chain signals."""

from internal.council.state_vector import _compute_dark_horse_score


def test_dark_horse_score_includes_crash_tail():
    sn = {
        "tao_pool": 0,
        "total_stake": 1,
        "circulating_supply": 0,
        "price_change_24h": -8.0,
        "price_change_7d": -12.0,
        "price_change_30d": -10.0,
    }
    score = _compute_dark_horse_score(sn)
    assert 0.0 <= score <= 1.0
    # Crash stress should lift score above pure-neutral on-chain fallback
    assert score > 0.45
