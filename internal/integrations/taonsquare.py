"""TaonSquare catalog — discovery layer for Bittensor subnet products.

Source: https://taonsquare.com/api (Yuma Group beta directory).
MCP: https://taonsquare.com/mcp
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

_CATALOG_URL = "https://taonsquare.com/api"
_CACHE_TTL = 300
_cache: Dict[str, Any] = {"at": 0.0, "rows": []}

# SimiVision dashboard fit — evidence, forecast, compute, finance, social data.
_RELEVANCE_KEYWORDS: Dict[str, int] = {
    "search": 5,
    "forecast": 5,
    "prediction": 5,
    "predictive": 4,
    "sentiment": 4,
    "social": 4,
    "inference": 3,
    "llm": 3,
    "compute": 3,
    "data": 3,
    "finance": 3,
    "trading": 3,
    "oracle": 4,
    "agent": 3,
    "memory": 4,
    "analytics": 3,
    "market": 3,
    "scraping": 3,
    "intelligence": 3,
}

# Override TaonSquare stale names (SN118 listed as HODL in beta catalog).
_NAME_OVERRIDES: Dict[int, str] = {118: "Ditto"}


def _normalize(entry: Dict[str, Any]) -> Dict[str, Any]:
    prod = entry.get("product") or {}
    access = entry.get("access") or {}
    links = entry.get("links") or {}
    pricing = entry.get("pricing") or {}
    on_chain = entry.get("on_chain") or {}
    netuid = entry.get("netuid")
    name = _NAME_OVERRIDES.get(netuid) or entry.get("name") or prod.get("name") or "?"
    return {
        "netuid": netuid,
        "name": name,
        "status": prod.get("status"),
        "category": prod.get("category") or "",
        "description": (prod.get("description") or "")[:200],
        "tags": prod.get("tags") or [],
        "api_available": bool(access.get("api_available")),
        "api_url": access.get("api_url") or links.get("api"),
        "docs_url": links.get("docs") or access.get("docs_url"),
        "website_url": links.get("website") or access.get("website"),
        "pricing_model": pricing.get("model"),
        "market_cap_tao": on_chain.get("market_cap_tao"),
        "source": "taonsquare",
    }


def fetch_catalog(*, force: bool = False) -> List[Dict[str, Any]]:
    """Return normalized TaonSquare subnet rows (cached 5 min)."""
    now = time.time()
    if not force and _cache["rows"] and now - _cache["at"] < _CACHE_TTL:
        return list(_cache["rows"])
    try:
        import requests

        resp = requests.get(_CATALOG_URL, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        raw = payload.get("subnets") or {}
        rows = [_normalize(v) for v in (raw.values() if isinstance(raw, dict) else raw)]
        _cache["at"] = now
        _cache["rows"] = rows
        return list(rows)
    except Exception as exc:
        logger.warning("TaonSquare catalog fetch failed: %s", exc)
        return list(_cache["rows"])


def _score_row(row: Dict[str, Any]) -> int:
    text = " ".join(
        [
            str(row.get("name") or ""),
            str(row.get("category") or ""),
            str(row.get("description") or ""),
            " ".join(row.get("tags") or []),
        ]
    ).lower()
    score = 0
    for kw, weight in _RELEVANCE_KEYWORDS.items():
        if kw in text:
            score += weight
    if row.get("api_available"):
        score += 6
    elif row.get("api_url"):
        score += 3
    if row.get("status") == "live":
        score += 2
    if row.get("docs_url"):
        score += 1
    return score


def recommend_candidates(
    *,
    exclude: Optional[Set[int]] = None,
    limit: int = 12,
) -> List[Dict[str, Any]]:
    """Rank TaonSquare subnets we could wire next (not yet in primary integrations)."""
    exclude = exclude or set()
    ranked: List[tuple[int, Dict[str, Any]]] = []
    for row in fetch_catalog():
        netuid = row.get("netuid")
        if netuid is None or netuid in exclude:
            continue
        if row.get("status") != "live":
            continue
        if not row.get("api_available") and not row.get("api_url"):
            continue
        s = _score_row(row)
        if s <= 0:
            continue
        ranked.append((s, {**row, "fit_score": s, "tier": "candidate"}))
    ranked.sort(key=lambda x: (-x[0], x[1].get("netuid") or 0))
    return [row for _, row in ranked[:limit]]


def catalog_summary() -> Dict[str, Any]:
    rows = fetch_catalog()
    live_api = [
        r
        for r in rows
        if r.get("status") == "live" and (r.get("api_available") or r.get("api_url"))
    ]
    return {
        "source": "taonsquare.com",
        "catalog_count": len(rows),
        "live_with_api": len(live_api),
        "mcp_url": "https://taonsquare.com/mcp",
    }
