"""Jinja context for message-intel (Phase M)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _subnet_name_lookup(subnets: List[Dict[str, Any]]) -> Dict[int, str]:
    names: Dict[int, str] = {}
    for sn in subnets:
        if not isinstance(sn, dict):
            continue
        nu = sn.get("netuid")
        if nu is None:
            continue
        try:
            names[int(nu)] = str(sn.get("name") or f"SN{nu}")
        except (TypeError, ValueError):
            continue
    return names


def lookup_social_sentiment_for_netuid(
    netuid: int,
    subnets: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Single-netuid sentiment from message_intel; None when no mentions."""
    try:
        nu = int(netuid)
    except (TypeError, ValueError):
        return None
    names = _subnet_name_lookup(subnets if isinstance(subnets, list) else [])
    try:
        from internal.message_intel.store import get_db

        for item in get_db().netuid_sentiment_rollup(limit=200):
            if int(item.get("netuid", -1)) != nu:
                continue
            mentions = int(item.get("mentions", 0) or 0)
            if mentions <= 0:
                return None
            return {
                "netuid": nu,
                "name": names.get(nu, f"SN{nu}"),
                "score": item.get("score", 0.5),
                "label": item.get("label", "neutral"),
                "mentions": mentions,
                "feed": [],
                "source": "message_intel",
            }
    except Exception as exc:
        logger.debug("social lookup for SN%s unavailable: %s", netuid, exc)
    return None


def _registry_social_row(
    netuid: int,
    subnets: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Fallback when message_intel is empty but registry has mention counts."""
    try:
        nu = int(netuid)
    except (TypeError, ValueError):
        return None
    names = _subnet_name_lookup(subnets)
    for sn in subnets:
        if not isinstance(sn, dict) or int(sn.get("netuid", -1)) != nu:
            continue
        mentions = int(sn.get("social_mentions", 0) or 0)
        if mentions <= 0:
            return None
        sent = float(sn.get("social_sentiment", 0.5) or 0.5)
        label = "bullish" if sent >= 0.6 else ("bearish" if sent <= 0.4 else "neutral")
        return {
            "netuid": nu,
            "name": names.get(nu, str(sn.get("name") or f"SN{nu}")),
            "score": sent,
            "label": label,
            "mentions": mentions,
            "feed": [],
            "source": "registry",
        }
    return None


def social_sentiment_for_home(
    subnets: Optional[List[Dict[str, Any]]] = None,
    *,
    pick_netuid: Optional[int] = None,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    """Homepage social rows — desk pick first when intel exists."""
    subnets = subnets if isinstance(subnets, list) else []
    rows = build_social_sentiment_rows(subnets, limit=limit)
    if pick_netuid is None:
        return rows

    pick_row = next((r for r in rows if r.get("netuid") == pick_netuid), None)
    if pick_row is None:
        pick_row = lookup_social_sentiment_for_netuid(pick_netuid, subnets)
    if pick_row is None:
        pick_row = _registry_social_row(pick_netuid, subnets)
    if pick_row is None:
        return rows

    rest = [r for r in rows if r.get("netuid") != pick_netuid]
    return [pick_row, *rest][:limit]


def build_social_sentiment_rows(
    subnets: Optional[List[Dict[str, Any]]] = None,
    *,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    """Per-subnet social sentiment from message_intel DB; honest-empty when unavailable."""
    subnets = subnets if isinstance(subnets, list) else []
    names = _subnet_name_lookup(subnets)
    try:
        from internal.message_intel.store import get_db

        db = get_db()
        rollup = db.netuid_sentiment_rollup(limit=max(limit, 6) * 4)
    except Exception as exc:
        logger.debug("social_sentiment rollup unavailable: %s", exc)
        return []

    rows: List[Dict[str, Any]] = []
    for item in rollup:
        netuid = item.get("netuid")
        if netuid is None:
            continue
        rows.append(
            {
                "netuid": netuid,
                "name": names.get(int(netuid), f"SN{netuid}"),
                "score": item.get("score", 0.5),
                "label": item.get("label", "neutral"),
                "mentions": int(item.get("mentions", 0) or 0),
                "feed": [],
            }
        )
        if len(rows) >= limit:
            break
    return rows


def build_message_intel_context(
    subnets: Optional[List[Dict[str, Any]]] = None,
    *,
    pick_netuid: Optional[int] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """Return message_intel panel data for GET /."""
    social_sentiment = social_sentiment_for_home(subnets, pick_netuid=pick_netuid, limit=6)
    try:
        from internal.message_intel.engine import list_messages
        from internal.message_intel.summary import summarize_message_intel

        listed = list_messages(limit=limit, offset=0)
        return {
            "message_intel": {
                "messages": listed.get("messages") or [],
                "meta": listed.get("meta") or {},
                "sources": listed.get("sources") or {},
                "summary": summarize_message_intel(),
            },
            "social_sentiment": social_sentiment,
        }
    except Exception as exc:
        logger.warning("message_intel context unavailable: %s", exc)
        return {
            "message_intel": {
                "messages": [],
                "meta": {"total_messages": 0, "ok": False},
                "sources": {},
                "summary": {
                    "text": "Message-intel warming up — social ingest unavailable on this deploy.",
                    "sentences": [],
                },
            },
            "social_sentiment": social_sentiment,
        }
