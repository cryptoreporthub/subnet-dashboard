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


def test_simivision_payload_exposes_call_line():
    rows = [
        {
            "netuid": 10,
            "name": "A",
            "emission": 1,
            "apy": 20,
            "volume": 9_000,
            "price": 1.0,
            "price_change_24h": 6.0,
            "market_cap": 1e6,
        },
    ]
    payload = _safe_simivision_payload(rows, source="test")
    top = payload["data"]["top"][0]
    assert top.get("reasons")
    assert top.get("call_line") == top["reasons"][0]
