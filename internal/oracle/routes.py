"""FastAPI read route for Oracle snapshot + judge backtest summary (Phase N1)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter

logger = logging.getLogger(__name__)

oracle_router = APIRouter(tags=["oracle"])


@oracle_router.get("/api/oracle")
async def api_oracle():
    """Oracle subnet snapshot plus latest judge backtest summary."""
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
        backtest_summary: Dict[str, Any] = {}
        try:
            from internal.analytics.backtest import run_backtest

            bt = run_backtest(limit=200)
            backtest_summary = {
                "sample_size": bt.get("sample_size"),
                "council_win_rate": (bt.get("council") or {}).get("win_rate"),
                "oracle_win_rate": (bt.get("judges") or {}).get("oracle", {}).get("win_rate"),
                "echo_win_rate": (bt.get("judges") or {}).get("echo", {}).get("win_rate"),
                "pulse_win_rate": (bt.get("judges") or {}).get("pulse", {}).get("win_rate"),
            }
        except Exception as bt_exc:
            logger.debug("oracle backtest summary skipped: %s", bt_exc)
        return {
            "status": "success",
            "source": source,
            "data": snapshot,
            "backtest": backtest_summary,
        }
    except Exception as exc:
        logger.warning("oracle snapshot failed: %s", exc)
        return {"status": "stub", "source": "error", "data": [], "backtest": {}, "error": str(exc)}
