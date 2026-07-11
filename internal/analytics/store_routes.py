"""Phase F — read/query API for Agent A's durable SQLite store (guarded)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

store_router = APIRouter(tags=["store"])


def _unavailable(detail: str) -> Dict[str, Any]:
    return {"status": "unavailable", "detail": detail}


@store_router.get("/api/store/trail")
async def api_store_trail(
    limit: int = Query(default=100, ge=1, le=500),
    signal: Optional[str] = Query(default=None),
):
    """Recent Soul-Map trail rows mirrored in SQLite."""
    try:
        from internal.store import get_trail_rows

        rows = get_trail_rows(limit=limit, signal=signal)
        return {"status": "success", "count": len(rows), "rows": rows}
    except ImportError as exc:
        return _unavailable(str(exc))
    except Exception as exc:
        logger.warning("store trail read failed: %s", exc)
        return _unavailable(str(exc))


@store_router.get("/api/store/dispositions")
async def api_store_dispositions():
    """Soul-Map disposition rows mirrored read-only from SQLite."""
    try:
        from internal.store import get_dispositions

        rows = get_dispositions()
        return {"status": "success", "count": len(rows), "dispositions": rows}
    except ImportError as exc:
        return _unavailable(str(exc))
    except Exception as exc:
        logger.warning("store dispositions read failed: %s", exc)
        return _unavailable(str(exc))


@store_router.get("/api/store/decision-lineage")
async def api_store_decision_lineage(limit: int = Query(default=100, ge=1, le=500)):
    """Decision lineage rows from the durable trace mirror."""
    try:
        from internal.store import get_decision_lineage

        rows = get_decision_lineage(limit=limit)
        return {"status": "success", "count": len(rows), "records": rows}
    except ImportError as exc:
        return _unavailable(str(exc))
    except Exception as exc:
        logger.warning("store decision-lineage read failed: %s", exc)
        return _unavailable(str(exc))


@store_router.get("/api/store/stats")
async def api_store_stats():
    """Aggregate SQLite store counters."""
    try:
        from internal.store import get_store_stats

        stats = get_store_stats()
        if not isinstance(stats, dict):
            stats = {}
        return {"status": "success", "stats": stats}
    except ImportError as exc:
        return _unavailable(str(exc))
    except Exception as exc:
        logger.warning("store stats read failed: %s", exc)
        return _unavailable(str(exc))
