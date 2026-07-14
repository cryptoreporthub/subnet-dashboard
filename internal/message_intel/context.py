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
    limit: int = 20,
) -> Dict[str, Any]:
    """Return message_intel panel data for GET /."""
    social_sentiment = build_social_sentiment_rows(subnets, limit=6)
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
