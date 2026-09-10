"""Derived counts for the authoritative subnet universe.

These helpers deliberately operate on the rows returned by /api/subnets rather
than config/registry.json so dashboard counts cannot drift from the displayed
universe. Root (SN0) is a real record but is reported separately from the
active application subnets.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable

ROOT_NETUID = 0

def netuid_of(row: Dict[str, Any]) -> int | None:
    for key in ("netuid", "id", "subnet_id"):
        value = row.get(key)
        if isinstance(value, bool):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None

def is_active(row: Dict[str, Any]) -> bool:
    value = row.get("status")
    if isinstance(value, str) and value.strip().lower() == "active":
        return True
    return row.get("active") is True

def summarize_subnets(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    records = [row for row in rows if isinstance(row, dict)]
    active = [row for row in records if is_active(row)]
    active_excluding_root = [
        row for row in active if netuid_of(row) != ROOT_NETUID
    ]
    root_present = any(netuid_of(row) == ROOT_NETUID for row in records)
    return {
        "total_subnets": len(records),
        "active_count": len(active),
        "active_count_excluding_root": len(active_excluding_root),
        "root_present": root_present,
        "root_netuid": ROOT_NETUID,
        "active_subnet_policy": "status=active; Root/SN0 excluded from active_count_excluding_root",
        "status_counts": dict(Counter(
            str(row.get("status") or "unknown") for row in records
        )),
    }
