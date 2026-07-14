"""Relative market impact: large caps dampened, small caps amplified."""

from internal.council.daily_pick import select_daily_pick
from internal.council.state_vector import score_subnet_for_day, score_subnet_for_hour
from internal.subnets.impact import (
    REFERENCE_TAO,
    impact_profile,
    impact_sensitivity,
    impact_tier,
    relative_flow,
    scale_move_by_impact,
    tao_order_impact_pct,
)


def _row(netuid, name, mcap, volume, **extra):
    base = {
        "netuid": netuid,
        "name": name,
        "symbol": name[:3].upper(),
        "emission": 2.0,
        "apy": 30.0,
        "volume": volume,
        "market_cap": mcap,
        "price": 1.0,
        "price_change_24h": 8.0,
        "price_change_7d": 10.0,
        "price_change_30d": 12.0,
        "status": "active",
    }
    base.update(extra)
    return base


def test_chutes_like_large_cap_has_tiny_tao_impact():
    chutes = _row(64, "Chutes", mcap=400_000, volume=1_700)
    micro = _row(15, "Thin", mcap=20_000, volume=50_000)
    assert tao_order_impact_pct(chutes, 100) < tao_order_impact_pct(micro, 50)
    assert impact_tier(chutes) == "large"
    assert impact_tier(micro) in ("mid", "small")
    assert impact_sensitivity(micro) > impact_sensitivity(chutes) * 5


def test_scale_move_dampens_large_caps():
    large = _row(64, "Chutes", mcap=400_000, volume=2_000)
    small = _row(99, "Small", mcap=10_000, volume=2_000)
    raw = 10.0
    assert abs(scale_move_by_impact(raw, large)) < abs(scale_move_by_impact(raw, small))


def test_relative_flow_not_absolute_volume():
    deep = _row(1, "Deep", mcap=400_000, volume=10_000)  # 2.5% of float
    thin = _row(2, "Thin", mcap=20_000, volume=5_000)  # 25% of float
    assert relative_flow(thin) > relative_flow(deep)


def test_day_score_prefers_impactful_flow_over_large_cap_emission():
    large = _row(64, "Chutes", mcap=400_000, volume=1_500, emission=8.0, price_change_24h=3.0)
    thin = _row(15, "Thin", mcap=18_000, volume=40_000, emission=1.0, price_change_24h=3.0)
    ctx = {"tao_change_24h": 0.0}
    large_score = score_subnet_for_day(large, ctx)["total_score"]
    thin_score = score_subnet_for_day(thin, ctx)["total_score"]
    assert thin_score > large_score


def test_hour_score_also_tilts_to_sensitive_names():
    large = _row(64, "Chutes", mcap=400_000, volume=1_500, emission=8.0, price_change_24h=10.0)
    thin = _row(15, "Thin", mcap=18_000, volume=40_000, emission=1.0, price_change_24h=10.0)
    ctx = {"tao_change_24h": 0.0}
    assert score_subnet_for_hour(thin, ctx)["total_score"] > score_subnet_for_hour(large, ctx)["total_score"]


def test_daily_pick_attaches_impact_block():
    large = _row(64, "Chutes", mcap=400_000, volume=1_500, emission=8.0)
    thin = _row(15, "Thin", mcap=18_000, volume=40_000, emission=1.5)
    pick = select_daily_pick([large, thin])
    assert pick["impact"] is not None
    assert pick["impact"]["ref_tao"] == REFERENCE_TAO
    assert "tier" in pick["impact"]
    # Thin name should win under impact-aware scoring
    assert pick["subnet"]["netuid"] == 15
    assert pick["impact"]["tier"] in ("small", "mid")


def test_impact_profile_summary():
    p = impact_profile(_row(64, "Chutes", mcap=400_000, volume=1_500), tao_amount=50)
    assert "float" in p["summary"]
    assert p["tier"] == "large"
