"""Ingest wallet events from TaoStats delegations into Whale Intelligence."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from internal.indicators.taostats_client import get_subnet_delegation_flow
from internal.whales.service import WhaleIntelligenceService

logger = logging.getLogger(__name__)

_WALLET_KEYS = (
    "coldkey", "cold_key", "delegator", "nominator", "hotkey", "hot_key",
    "ss58", "address", "wallet", "account", "owner",
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
    return "buy"


def _extract_amount(row: Dict[str, Any]) -> float:
    for key in ("amount", "tao", "value", "stake", "quantity"):
        val = row.get(key)
        if isinstance(val, (int, float)):
            return abs(float(val))
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
    return []


def scan_subnet_delegations(
    netuid: int,
    service: Optional[WhaleIntelligenceService] = None,
    subnet_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    service = service or WhaleIntelligenceService()
    meta = subnet_meta or {}
    payload = get_subnet_delegation_flow(netuid)
    rows = _normalize_rows(payload)

    ingested = 0
    skipped = 0

    for row in rows:
        wallet = _extract_wallet(row)
        if not wallet:
            skipped += 1
            continue
        side = _infer_side(row)
        amount = _extract_amount(row)
        if amount <= 0:
            skipped += 1
            continue
        try:
            result = service.record_event(
                wallet=wallet,
                netuid=netuid,
                side=side,
                amount_tao=amount,
                timestamp=_extract_timestamp(row),
                source="taostats_delegation",
                tx_hash=row.get("tx_hash") or row.get("hash"),
                subnet_name=meta.get("name"),
                entry_price=meta.get("price") if side == "buy" else None,
                exit_price=meta.get("price") if side == "sell" else None,
                market_cap_rank=meta.get("emission_rank") or meta.get("rank"),
                total_stake_tao=meta.get("total_stake") or meta.get("staking_data", {}).get("total_stake"),
                price_change_after_hours=row.get("price_change_24h"),
            )
            if result.get("status") == "recorded":
                ingested += 1
        except Exception as exc:
            logger.debug("whale ingest skip netuid=%s: %s", netuid, exc)
            skipped += 1

    return {
        "netuid": netuid,
        "rows_seen": len(rows),
        "ingested": ingested,
        "skipped": skipped,
        "has_wallet_data": ingested > 0 or any(_extract_wallet(r) for r in rows),
    }


def scan_netuids(
    netuids: List[int],
    subnet_meta_by_id: Optional[Dict[int, Dict[str, Any]]] = None,
    service: Optional[WhaleIntelligenceService] = None,
) -> Dict[str, Any]:
    service = service or WhaleIntelligenceService()
    subnet_meta_by_id = subnet_meta_by_id or {}
    per_subnet = []
    total_ingested = 0

    for netuid in netuids:
        try:
            result = scan_subnet_delegations(
                netuid,
                service=service,
                subnet_meta=subnet_meta_by_id.get(netuid, {}),
            )
            per_subnet.append(result)
            total_ingested += int(result.get("ingested", 0))
        except Exception as exc:
            logger.warning("whale scan failed netuid=%s: %s", netuid, exc)
            per_subnet.append({"netuid": netuid, "error": str(exc)})

    return {
        "status": "success",
        "scanned": len(netuids),
        "ingested": total_ingested,
        "subnets": per_subnet,
        "summary": service.summary(),
    }
