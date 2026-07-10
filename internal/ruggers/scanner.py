"""
Poll TaoStats delegation flows and ingest wallet-level buy/sell events.

TaoStats delegation payloads vary; we extract wallet addresses from common
field names and infer side from direction/action fields.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from internal.indicators.taostats_client import get_subnet_delegation_flow
from internal.ruggers.watchlist import RuggerWatchlist

logger = logging.getLogger(__name__)

_WALLET_KEYS = (
    "coldkey",
    "cold_key",
    "delegator",
    "nominator",
    "hotkey",
    "hot_key",
    "ss58",
    "address",
    "wallet",
    "account",
    "owner",
)

_BUY_TOKENS = ("stake", "buy", "add", "delegate", "in", "incoming", "deposit")
_SELL_TOKENS = ("unstake", "sell", "remove", "undelegate", "out", "outgoing", "withdraw")


def _extract_wallet(row: Dict[str, Any]) -> Optional[str]:
    for key in _WALLET_KEYS:
        val = row.get(key)
        if isinstance(val, str) and len(val) >= 8:
            return val
        if isinstance(val, dict):
            nested = val.get("ss58") or val.get("address")
            if isinstance(nested, str) and len(nested) >= 8:
                return nested
    return None


def _infer_side(row: Dict[str, Any]) -> Optional[str]:
    for field in ("direction", "action", "type", "side", "flow"):
        raw = str(row.get(field, "")).lower()
        if any(tok in raw for tok in _BUY_TOKENS):
            return "buy"
        if any(tok in raw for tok in _SELL_TOKENS):
            return "sell"
    amount = row.get("amount")
    if isinstance(amount, (int, float)) and amount < 0:
        return "sell"
    return "buy"


def _extract_amount(row: Dict[str, Any]) -> float:
    for key in ("amount", "tao", "value", "stake", "quantity"):
        val = row.get(key)
        if isinstance(val, (int, float)):
            return abs(float(val))
        if isinstance(val, str):
            try:
                return abs(float(val))
            except ValueError:
                pass
    return 0.0


def _extract_timestamp(row: Dict[str, Any]) -> Optional[str]:
    for key in ("timestamp", "block_time", "created_at", "time", "date"):
        val = row.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def _normalize_rows(payload: Any) -> List[Dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("data", "delegations", "items", "results"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [r for r in inner if isinstance(r, dict)]
            if isinstance(inner, dict):
                return [inner]
    return []


def scan_subnet_delegations(
    netuid: int,
    watchlist: Optional[RuggerWatchlist] = None,
    subnet_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch TaoStats delegations for one subnet and ingest wallet events."""
    watchlist = watchlist or RuggerWatchlist()
    payload = get_subnet_delegation_flow(netuid)
    rows = _normalize_rows(payload)

    ingested = 0
    skipped = 0
    results: List[Dict[str, Any]] = []

    for row in rows:
        wallet = _extract_wallet(row)
        if not wallet:
            skipped += 1
            continue
        side = _infer_side(row)
        if not side:
            skipped += 1
            continue
        amount = _extract_amount(row)
        if amount <= 0:
            skipped += 1
            continue
        try:
            result = watchlist.record_event(
                wallet=wallet,
                netuid=netuid,
                side=side,
                amount_tao=amount,
                timestamp=_extract_timestamp(row),
                source="taostats_delegation",
                tx_hash=row.get("tx_hash") or row.get("hash"),
                subnet_name=subnet_name,
            )
            if result.get("status") == "recorded":
                ingested += 1
                results.append(result)
        except Exception as exc:
            logger.debug("rugger ingest skip netuid=%s: %s", netuid, exc)
            skipped += 1

    return {
        "netuid": netuid,
        "rows_seen": len(rows),
        "ingested": ingested,
        "skipped": skipped,
        "has_wallet_data": ingested > 0 or any(_extract_wallet(r) for r in rows),
    }


def scan_watchlist_netuids(
    netuids: List[int],
    subnet_names: Optional[Dict[int, str]] = None,
    watchlist: Optional[RuggerWatchlist] = None,
) -> Dict[str, Any]:
    """Scan a list of netuids for delegation-based rugger signals."""
    watchlist = watchlist or RuggerWatchlist()
    subnet_names = subnet_names or {}
    per_subnet = []
    total_ingested = 0

    for netuid in netuids:
        try:
            result = scan_subnet_delegations(
                netuid,
                watchlist=watchlist,
                subnet_name=subnet_names.get(netuid),
            )
            per_subnet.append(result)
            total_ingested += int(result.get("ingested", 0))
        except Exception as exc:
            logger.warning("rugger scan failed netuid=%s: %s", netuid, exc)
            per_subnet.append({"netuid": netuid, "error": str(exc)})

    return {
        "status": "success",
        "scanned": len(netuids),
        "ingested": total_ingested,
        "subnets": per_subnet,
        "summary": watchlist.summary(),
    }
