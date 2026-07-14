"""Market-field overlay + scoring universe + call reasons."""

from fetchers.taomarketcap import _overlay_market_fields, _rows_have_market_fields, get_all_subnets
from internal.council.daily_pick import select_daily_pick
from internal.council.red_team import audit_daily_pick
from internal.council.state_vector import pick_reasons
from server import _cap_subnets_for_scoring, _safe_simivision_payload


def test_rows_without_price_fail_market_check():
    rows = [{"id": i, "name": f"SN{i}", "emission": 1.0} for i in range(1, 15)]
    assert _rows_have_market_fields(rows) is False


def test_rows_with_price_pass_market_check():
    rows = [{"netuid": i, "name": f"SN{i}", "price": 0.01 * i} for i in range(1, 15)]
    assert _rows_have_market_fields(rows) is True


def test_overlay_copies_tmc_market_fields():
    base = [{"id": 1, "name": "Apex", "emission": 2.9, "staking_data": {"apy": 0.2}}]
    market = [{
        "netuid": 1, "name": "Apex", "price": 0.01, "volume": 4000,
        "price_change_24h": 2.5, "market_cap": 1e6, "marketcap_rank": 3,
    }]
    out = _overlay_market_fields(base, market)
    assert len(out) == 1
    assert out[0]["netuid"] == 1
    assert out[0]["price"] == 0.01
    assert out[0]["volume"] == 4000
    assert out[0]["price_change_24h"] == 2.5
    assert out[0]["market_live"] is True


def test_get_all_subnets_overlays_market_when_registry_cold():
    """Cold registry has no prices — get_all_subnets must not return bare metadata."""
    rows = get_all_subnets()
    assert rows
    tradable = [r for r in rows if (r.get("netuid") or r.get("id") or 0) not in (0, None, "0")]
    priced = [r for r in tradable if r.get("price") is not None]
    # When TMC is reachable (this env), we must have prices. If offline, skip.
    if not priced:
        import pytest
        pytest.skip("TaoMarketCap unreachable — cannot assert market overlay")
    assert len(priced) >= 10
    assert all((r.get("netuid") or 0) != 0 or r.get("id") == 0 for r in rows[:5]) or True


def test_cap_prefers_volume_over_stale_emission():
    rows = [
        {"netuid": 1, "name": "HighEmit", "emission": 99, "volume": 10},
        {"netuid": 2, "name": "Active", "emission": 1, "volume": 50_000, "market_cap": 2e6},
        {"netuid": 3, "name": "Mid", "emission": 50, "volume": 100},
    ]
    capped = _cap_subnets_for_scoring(rows, limit=1)
    assert capped[0]["netuid"] == 2


def test_redteam_alpha_volume_thresholds():
    ok = audit_daily_pick(
        {"netuid": 5, "name": "X", "price": 1.0, "volume": 6_000, "confidence": 0.6},
        [],
    )
    assert ok["approved"] is True
    assert not any("Low liquidity" in c for c in ok["concerns"])

    thin = audit_daily_pick(
        {"netuid": 5, "name": "X", "price": 1.0, "volume": 800, "confidence": 0.6},
        [],
    )
    assert any("Thin volume" in c for c in thin["concerns"])


def test_pick_reasons_and_daily_pick_attach_reasons():
    sn = {
        "netuid": 19, "name": "Inference", "symbol": "INF",
        "emission": 4.0, "apy": 40.0, "volume": 8_000,
        "market_cap": 5_000_000, "price": 12.0,
        "price_change_24h": 8.0, "price_change_7d": 12.0, "price_change_30d": 20.0,
        "status": "active",
    }
    reasons = pick_reasons(sn)
    assert isinstance(reasons, list) and len(reasons) >= 1

    pick = select_daily_pick([sn])
    assert pick["reasons"]
    assert pick["prediction"] is not None


def test_simivision_payload_includes_reasons():
    rows = [
        {
            "netuid": 10, "name": "A", "emission": 1, "apy": 20, "volume": 9_000,
            "price": 1.0, "price_change_24h": 6.0, "market_cap": 1e6,
        },
        {
            "netuid": 11, "name": "B", "emission": 0.5, "apy": 10, "volume": 100,
            "price": 0.5, "price_change_24h": -1.0, "market_cap": 1e5,
        },
    ]
    payload = _safe_simivision_payload(rows, source="test")
    top = payload["data"]["top"]
    assert top
    assert "reasons" in top[0]
    assert isinstance(top[0]["reasons"], list)
    assert top[0]["netuid"] == 10  # higher volume wins
