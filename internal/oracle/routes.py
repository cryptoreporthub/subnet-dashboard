"""FastAPI read route for the Oracle snapshot stub (slice 9)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter

logger = logging.getLogger(__name__)

oracle_router = APIRouter(tags=["oracle"])


@oracle_router.get("/api/oracle")
async def api_oracle():
    """Return a minimal oracle snapshot from live subnet data."""
    try:
        from server import _get_subnets_with_source

        subnets, source = _get_subnets_with_source()
        snapshot: List[Dict[str, Any]] = [
            {
                "netuid": s.get("netuid"),
                "name": s.get("name"),
                "symbol": s.get("symbol"),
                "price": s.get("price"),
                "price_change_24h": s.get("price_change_24h"),
            }
            for s in subnets[:10]
        ]
        return {"status": "success", "source": source, "data": snapshot}
    except Exception as exc:
        logger.warning("oracle snapshot failed: %s", exc)
        return {"status": "stub", "source": "error", "data": [], "error": str(exc)}
