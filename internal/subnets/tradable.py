"""Tradable subnet universe — Root (netuid 0) is never a pick.

Root is how you stake TAO on the chain, not a subnet alpha market. Registry
rows often use ``id`` without ``netuid``; live feeds may include netuid 0.
Counting Root as a subnet inflates the universe (e.g. 129 vs 128).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def subnet_netuid(sn: Dict[str, Any]) -> Optional[int]:
    """Resolve numeric netuid from ``netuid`` or registry ``id``."""
    if not isinstance(sn, dict):
        return None
    raw = sn.get("netuid")
    if raw is None:
        raw = sn.get("id")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def is_tradable_subnet(sn: Dict[str, Any]) -> bool:
    """True when netuid is a positive subnet id (excludes Root / missing)."""
    n = subnet_netuid(sn)
    return n is not None and n > 0


def normalize_subnet_row(sn: Dict[str, Any]) -> Dict[str, Any]:
    """Copy row with ``netuid`` filled from ``id`` when missing."""
    row = dict(sn) if isinstance(sn, dict) else {}
    n = subnet_netuid(row)
    if n is not None and row.get("netuid") is None:
        row["netuid"] = n
    return row


def tradable_subnets(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize and drop Root / invalid rows. Dedupes by netuid (last wins)."""
    out: Dict[int, Dict[str, Any]] = {}
    for sn in rows or []:
        row = normalize_subnet_row(sn)
        if not is_tradable_subnet(row):
            continue
        out[int(row["netuid"])] = row
    return list(out.values())


def subnet_volume(sn: Dict[str, Any]) -> float:
    """Unified 24h turnover — ``volume`` or buy+sell chain volumes."""
    if not isinstance(sn, dict):
        return 0.0
    raw = sn.get("volume")
    if raw is not None and raw != "":
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    try:
        buy = float(sn.get("buy_volume_24h") or 0)
        sell = float(sn.get("sell_volume_24h") or 0)
        return buy + sell
    except (TypeError, ValueError):
        return 0.0
