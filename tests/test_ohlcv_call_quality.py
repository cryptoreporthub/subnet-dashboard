"""Residual call-quality: priced scoring preference + SimiVision call lines.

Lazy OHLCV itself landed in #212; this covers the remaining gaps.
"""

from __future__ import annotations

from server import _cap_subnets_for_scoring, _safe_simivision_payload


def test_cap_prefers_priced_over_cold_emission():
    rows = [
        {"netuid": 1, "name": "Cold", "emission": 99.0, "volume": 0, "market_cap": 0},
        {
            "netuid": 2,
            "name": "Live",
            "emission": 1.0,
            "volume": 5_000,
            "market_cap": 50_000,
            "price": 1.2,
        },
    ]
    capped = _cap_subnets_for_scoring(rows, limit=1)
    assert capped[0]["netuid"] == 2


def test_simivision_payload_exposes_council_reason():
    rows = [
        {
            "netuid": 1,
            "name": "Alpha",
            "emission": 1,
            "apy": 20,
            "volume": 9_000,
            "price": 1.0,
            "price_change_24h": 6.0,
            "market_cap": 1e6,
        },
        {
            "netuid": 2,
            "name": "Beta",
            "emission": 1,
            "apy": 18,
            "volume": 8_000,
            "price": 0.9,
            "price_change_24h": 4.0,
            "market_cap": 9e5,
        },
        {
            "netuid": 3,
            "name": "Gamma",
            "emission": 1,
            "apy": 16,
            "volume": 7_000,
            "price": 0.8,
            "price_change_24h": 2.0,
            "market_cap": 8e5,
        },
    ]
    daily = {
        "pick": {
            "subnet": {"netuid": 1, "name": "Alpha"},
            "final_confidence": 0.78,
            "expert_contributions": {"quant": 0.4, "hype": 0.2},
            "audit": {"concerns": []},
        }
    }
    payload = _safe_simivision_payload(rows, source="test", daily_pick=daily, market_context={})
    top = payload["data"]["top"]
    assert top
    assert top[0].get("reason")
    assert payload["data"]["meta"]["source"] == "council-shortlist"
    assert all(t["netuid"] != 1 for t in top)


def test_simivision_honest_empty_when_shortlist_thin():
    rows = [
        {"netuid": 0, "name": "Root", "emission": 99, "volume": 1e9, "apy": 25, "status": "active"},
        {"netuid": 3, "name": "Templar", "emission": 1, "volume": 100, "apy": 20, "status": "deprecated"},
        {"netuid": 51, "name": "Compute", "emission": 8, "volume": 5000, "apy": 17, "status": "active"},
    ]
    top = _safe_simivision_payload(rows, source="test")["data"]["top"]
    assert top == []
