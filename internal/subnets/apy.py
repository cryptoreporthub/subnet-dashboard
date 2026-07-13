"""Normalize subnet APY for display (registry fraction vs TaoMarketCap percent)."""

from __future__ import annotations

from typing import Any, Dict, Optional


def apy_as_percent(value: Any, *, from_fraction: bool = False) -> Optional[float]:
    """Return APY as a human percent (e.g. 24.7), not a 0–1 fraction."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if from_fraction or (0 < v <= 1.0):
        return round(v * 100.0, 2)
    return round(v, 2)


def subnet_apy_percent(sn: Dict[str, Any]) -> Optional[float]:
    """Best-effort APY percent for a subnet dict from registry or TaoMarketCap."""
    staking = sn.get("staking_data")
    if isinstance(staking, dict) and staking.get("apy") is not None:
        return apy_as_percent(staking["apy"], from_fraction=True)
    if sn.get("apy") is not None:
        return apy_as_percent(sn["apy"])
    return None


def undervalued_score(sn: Dict[str, Any]) -> Optional[float]:
    """Yield minus 24h price change (percent points). Higher = more undervalued."""
    apy = subnet_apy_percent(sn)
    if apy is None:
        return None
    chg24 = float(sn.get("price_change_24h", 0) or 0)
    return round(apy - chg24, 2)


def undervalued_verdict(sn: Dict[str, Any]) -> str:
    """Council undervalued label: strong yield vs lagging 24h price."""
    score = undervalued_score(sn)
    if score is None:
        return "unknown"
    if score > 15:
        return "deep_value"
    if score > 5:
        return "value"
    if score < 0:
        return "rich"
    return "fair"
