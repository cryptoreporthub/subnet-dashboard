"""P0.6 — hype price momentum must keep sign (no abs() inversion)."""

from __future__ import annotations

import pytest

from internal.council.state_vector import _expert_contributions, _hype_price_momentum


def test_positive_momentum_stays_positive_magnitude_preserved():
    # +20% 24h → raw 1.0 → magnitude-capped +0.20 (same ceiling as pre-fix)
    assert _hype_price_momentum(20.0, 0.0) == pytest.approx(0.20)
    assert _hype_price_momentum(20.0, 0.0) > 0.0
    # Inside the cap: +2% 24h → 0.10 exactly (magnitude preserved, not zeroed)
    assert _hype_price_momentum(2.0, 0.0) == pytest.approx(0.10)
    # +2% 24h + +3% 7d → 0.10 + 0.05 = 0.15
    assert _hype_price_momentum(2.0, 3.0) == pytest.approx(0.15)


def test_negative_momentum_stays_negative_no_inversion():
    # Reproduction input: −40%/24h previously became +0.20 via abs().
    assert _hype_price_momentum(-40.0, 0.0) == pytest.approx(-0.20)
    assert _hype_price_momentum(-40.0, 0.0) < 0.0
    # Inside-cap negative: −2% 24h → −0.10 (magnitude preserved, not floored to 0)
    assert _hype_price_momentum(-2.0, 0.0) == pytest.approx(-0.10)
    # Negative 7d alone: −6%/7d → −0.10
    assert _hype_price_momentum(0.0, -6.0) == pytest.approx(-0.10)
    # Large negative 7d hits the same magnitude ceiling: −30/60 = −0.5 → −0.20
    assert _hype_price_momentum(0.0, -30.0) == pytest.approx(-0.20)
    # Mixed cancel: +2% 24h and −6% 7d → 0.10 − 0.10 = 0.0
    assert _hype_price_momentum(2.0, -6.0) == pytest.approx(0.0)


def test_zero_change_is_clean_zero():
    assert _hype_price_momentum(0.0, 0.0) == 0.0


def test_reproduction_dump_no_longer_boosts_hype_expert():
    """Exact pre-fix inversion case: dump earned max positive mom via abs()."""
    sn_dump = {
        "netuid": 9,
        "emission": 0.0,
        "apy": 0.0,
        "price": 1.0,
        "volume": 0.0,
        "market_cap": 1.0,
        "social_mentions": 0,
        "price_change_24h": -40.0,
        "price_change_7d": 0.0,
    }
    sn_flat = dict(sn_dump, price_change_24h=0.0)
    sn_up = dict(sn_dump, price_change_24h=20.0)
    empty: dict = {}
    dump = _expert_contributions(sn_dump, empty, {}, empty, empty)
    flat = _expert_contributions(sn_flat, empty, {}, empty, empty)
    up = _expert_contributions(sn_up, empty, {}, empty, empty)
    assert dump["hype"] < flat["hype"]
    assert up["hype"] > dump["hype"]
    assert up["hype"] > flat["hype"]
    # Magnitude preserved across the sign flip at the ±0.20 ceiling
    assert abs(_hype_price_momentum(-40.0, 0.0)) == pytest.approx(
        _hype_price_momentum(20.0, 0.0)
    )
