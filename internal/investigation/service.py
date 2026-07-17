"""On-chain investigation queries (TaoStats-backed)."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

CACHE_DB = os.environ.get("INVESTIGATION_CACHE_DB", "data/investigation_cache.db")
CACHE_TTL_SECONDS = int(os.environ.get("INVESTIGATION_CACHE_TTL", "180"))

_SELL_TOKENS = ("unstake", "sell", "remove", "undelegate", "out", "withdraw")
_BUY_TOKENS = ("stake", "buy", "add", "delegate", "in", "deposit")
_WALLET_KEYS = (
    "coldkey", "cold_key", "delegator", "nominator", "hotkey", "ss58", "address", "wallet",
)


def _records(payload: Any) -> List[Dict[str, Any]]:
    if not payload:
        return []
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "items", "delegations", "transfers", "events"):
            val = payload.get(key)
            if isinstance(val, list):
                return [r for r in val if isinstance(r, dict)]
        return [payload]
    return []


def _wallet(row: Dict[str, Any]) -> Optional[str]:
    for key in _WALLET_KEYS:
        val = row.get(key)
        if isinstance(val, str) and len(val) >= 8:
            return val
    return None


def _side(row: Dict[str, Any]) -> str:
    for field in ("direction", "action", "type", "side", "flow"):
        raw = str(row.get(field, "")).lower()
        if any(tok in raw for tok in _SELL_TOKENS):
            return "sell"
        if any(tok in raw for tok in _BUY_TOKENS):
            return "buy"
    return "unknown"


def _amount(row: Dict[str, Any]) -> float:
    for key in ("amount", "tao", "value", "stake", "quantity", "amount_tao"):
        val = row.get(key)
        if isinstance(val, (int, float)):
            return abs(float(val))
    return 0.0


def _normalize_event(row: Dict[str, Any], netuid: Optional[int] = None) -> Dict[str, Any]:
    return {
        "wallet": _wallet(row),
        "netuid": row.get("netuid", netuid),
        "side": _side(row),
        "amount_tao": _amount(row),
        "timestamp": row.get("timestamp") or row.get("block_time") or row.get("date"),
        "tx_hash": row.get("tx_hash") or row.get("extrinsic_id") or row.get("hash"),
        "is_transfer": row.get("is_transfer"),
        "transfer_address": row.get("transfer_address") or row.get("to"),
        "raw_action": row.get("action") or row.get("direction") or row.get("type"),
    }


def _init_cache_db() -> None:
    os.makedirs(os.path.dirname(CACHE_DB) or ".", exist_ok=True)
    conn = sqlite3.connect(CACHE_DB)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS investigation_cache (
            cache_key TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            cached_at REAL NOT NULL
        )"""
    )
    conn.commit()
    conn.close()


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    try:
        conn = sqlite3.connect(CACHE_DB)
        row = conn.execute(
            "SELECT payload, cached_at FROM investigation_cache WHERE cache_key = ?", (key,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        payload, cached_at = row
        if time.time() - float(cached_at) > CACHE_TTL_SECONDS:
            return None
        return json.loads(payload)
    except Exception:
        return None


def _cache_set(key: str, data: Dict[str, Any]) -> None:
    try:
        _init_cache_db()
        conn = sqlite3.connect(CACHE_DB)
        conn.execute(
            "INSERT OR REPLACE INTO investigation_cache (cache_key, payload, cached_at) VALUES (?, ?, ?)",
            (key, json.dumps(data), time.time()),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.debug("investigation cache write failed: %s", exc)


def _cached(key: str, fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    hit = _cache_get(key)
    if hit is not None:
        hit["cached"] = True
        return hit
    result = fn()
    if isinstance(result, dict) and result.get("status") == "success":
        result["cached"] = False
        _cache_set(key, result)
    return result


def investigate_subnet_sellers(netuid: int, *, limit: int = 50) -> Dict[str, Any]:
    return _cached(f"sellers:{netuid}:{limit}", lambda: _investigate_subnet_sellers(netuid, limit=limit))


def _investigate_subnet_sellers(netuid: int, *, limit: int = 50) -> Dict[str, Any]:
    from fetchers.taostats_client import get_delegation_events, get_subnet_delegation_flow, is_available

    if not is_available():
        return {
            "status": "unavailable",
            "netuid": netuid,
            "message": "TAOSTATS_API_KEY not set",
            "sellers": [],
            "unique_wallets": 0,
        }

    payload = get_delegation_events(netuid=netuid, action="all", limit=limit)
    rows = _records(payload)
    if not rows:
        payload = get_subnet_delegation_flow(netuid, limit=limit)
        rows = _records(payload)

    events = [_normalize_event(r, netuid) for r in rows]
    sells = [e for e in events if e["side"] == "sell" and e["amount_tao"] > 0]
    sells.sort(key=lambda e: e["amount_tao"], reverse=True)

    by_wallet: Dict[str, float] = {}
    for e in sells:
        w = e.get("wallet")
        if w:
            by_wallet[w] = by_wallet.get(w, 0.0) + e["amount_tao"]

    ranked = [
        {"wallet": w, "total_tao": round(v, 6), "sell_count": sum(1 for e in sells if e.get("wallet") == w)}
        for w, v in sorted(by_wallet.items(), key=lambda x: x[1], reverse=True)
    ]

    return {
        "status": "success",
        "netuid": netuid,
        "sell_events": sells[:limit],
        "top_sellers": ranked[:25],
        "unique_wallets": len(by_wallet),
        "total_sell_events": len(sells),
        "multiple_wallets": len(by_wallet) > 1,
    }


def investigate_wallet(wallet: str, *, limit: int = 50) -> Dict[str, Any]:
    return _cached(f"wallet:{wallet}:{limit}", lambda: _investigate_wallet(wallet, limit=limit))


def _investigate_wallet(wallet: str, *, limit: int = 50) -> Dict[str, Any]:
    from fetchers.taostats_client import get_account, get_delegation_events, get_transfers, is_available

    if not is_available():
        return {"status": "unavailable", "wallet": wallet, "message": "TAOSTATS_API_KEY not set"}

    delegations = _records(get_delegation_events(nominator=wallet, limit=limit))
    transfers_out = _records(get_transfers(from_wallet=wallet, limit=limit))
    transfers_in = _records(get_transfers(to_wallet=wallet, limit=limit))
    account = get_account(wallet)

    events = [_normalize_event(r) for r in delegations]
    sells = [e for e in events if e["side"] == "sell"]
    buys = [e for e in events if e["side"] == "buy"]

    return {
        "status": "success",
        "wallet": wallet,
        "account": account,
        "delegation_events": events,
        "sells": sells,
        "buys": buys,
        "transfers_out": transfers_out[:limit],
        "transfers_in": transfers_in[:limit],
        "sell_total_tao": round(sum(e["amount_tao"] for e in sells), 6),
        "buy_total_tao": round(sum(e["amount_tao"] for e in buys), 6),
    }


def trace_wallet_flow(
    wallet: str,
    *,
    counterparty: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    key = f"flow:{wallet}:{counterparty or ''}:{limit}"
    return _cached(key, lambda: _trace_wallet_flow(wallet, counterparty=counterparty, limit=limit))


def _trace_wallet_flow(
    wallet: str,
    *,
    counterparty: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    base = _investigate_wallet(wallet, limit=limit)
    if base.get("status") != "success":
        return base

    transfer_links: List[Dict[str, Any]] = []
    for row in base.get("transfers_out") or []:
        dest = row.get("to") or row.get("destination") or row.get("transfer_address")
        if isinstance(dest, str):
            transfer_links.append({"from": wallet, "to": dest, "row": row})

    delegation_transfers = [
        e for e in base.get("delegation_events") or []
        if e.get("is_transfer") or e.get("transfer_address")
    ]

    counterparty_activity = None
    if counterparty:
        counterparty_activity = _investigate_wallet(counterparty, limit=limit)
        transfer_links = [t for t in transfer_links if t.get("to") == counterparty]

    return {
        "status": "success",
        "wallet": wallet,
        "counterparty": counterparty,
        "transfer_links": transfer_links[:limit],
        "delegation_transfers": delegation_transfers[:limit],
        "counterparty_activity": counterparty_activity,
        "sell_total_tao": base.get("sell_total_tao"),
        "buy_total_tao": base.get("buy_total_tao"),
    }


def investigate_owner_check(netuid: int, wallets: List[str]) -> Dict[str, Any]:
    from fetchers.taostats_client import get_subnet_owner, is_available

    if not is_available():
        return {"status": "unavailable", "netuid": netuid, "message": "TAOSTATS_API_KEY not set"}

    owner_payload = get_subnet_owner(netuid)
    owner = None
    for row in _records(owner_payload):
        owner = _wallet(row) or row.get("owner") or row.get("coldkey")
        if owner:
            break
    if not owner and isinstance(owner_payload, dict):
        owner = owner_payload.get("owner") or owner_payload.get("coldkey")

    normalized = [w.strip() for w in wallets if w and w.strip()]
    matches = [w for w in normalized if owner and w == owner]

    sellers = investigate_subnet_sellers(netuid, limit=50)
    seller_wallets = {s["wallet"] for s in sellers.get("top_sellers", []) if s.get("wallet")}
    suspect_in_sellers = [w for w in normalized if w in seller_wallets]

    return {
        "status": "success",
        "netuid": netuid,
        "owner": owner,
        "suspect_wallets": normalized,
        "owner_matches": matches,
        "suspects_among_sellers": suspect_in_sellers,
        "owner_is_seller": bool(matches and suspect_in_sellers),
    }


def build_investigation_report(question: str, *, netuid: Optional[int] = None, wallet: Optional[str] = None) -> Dict[str, Any]:
    """Structured facts for chat / API (not LLM prose)."""
    parts: Dict[str, Any] = {"question": question, "sections": []}
    q = (question or "").lower()

    if netuid is not None or "subnet" in q or "sn" in q:
        n = netuid
        if n is None:
            import re
            m = re.search(r"\b(?:sn|subnet)\s*(\d+)\b", q, re.I)
            if m:
                n = int(m.group(1))
        if n is not None:
            sellers = investigate_subnet_sellers(n)
            parts["sections"].append({"type": "subnet_sellers", "data": sellers})
            if wallet or "owner" in q:
                wallets = [wallet] if wallet else []
                parts["sections"].append({"type": "owner_check", "data": investigate_owner_check(n, wallets)})

    if wallet:
        parts["sections"].append({"type": "wallet_activity", "data": investigate_wallet(wallet)})
        if "transfer" in q or "flow" in q or "trace" in q:
            parts["sections"].append({"type": "wallet_flow", "data": trace_wallet_flow(wallet)})

    return parts
