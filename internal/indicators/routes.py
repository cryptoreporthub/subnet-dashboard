"""FastAPI read routes for the technical indicator layer (slice 7)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter

from internal.council.state_vector import (
    _compute_technical_indicators,
    _detect_overbought_convergence,
    _detect_oversold_convergence,
    _get_price_history,
)
from internal.indicators.indicator_engine import IndicatorEngine
from internal.indicators.indicator_scheduler import get_indicator_scheduler_state

logger = logging.getLogger(__name__)

indicators_router = APIRouter(tags=["indicators"])


@indicators_router.get("/api/indicators")
async def api_indicators():
    """Return the latest technical-indicator state from the indicator engine."""
    try:
        return {
            "status": "success",
            "data": IndicatorEngine().get_indicator_state(),
        }
    except Exception as exc:
        logger.error("Error fetching indicator state: %s", exc)
        return {"status": "error", "data": {}, "error": str(exc)}


@indicators_router.get("/api/indicators-convergence")
async def api_indicators_convergence():
    """Return multi-indicator oversold/overbought convergence for top subnets."""
    try:
        from server import _get_subnets_with_source

        subnets, _ = _get_subnets_with_source()
        ranked = sorted(
            subnets,
            key=lambda s: (s.get("emission", 0), s.get("apy", 0), s.get("volume", 0)),
            reverse=True,
        )
        rows: List[Dict[str, Any]] = []
        for sn in ranked[:6]:
            indicators = _compute_technical_indicators(sn)
            hist = _get_price_history(sn.get("netuid"), sn)
            sparks = hist.get("closes") or []
            if hist.get("source") in ("synthetic", "unavailable") or len(sparks) < 2:
                sparks = []
            else:
                sparks = [float(c) for c in sparks[-24:]]
            rows.append(
                {
                    "netuid": sn.get("netuid"),
                    "name": sn.get("name"),
                    "oversold": _detect_oversold_convergence(indicators),
                    "overbought": _detect_overbought_convergence(indicators),
                    "spark_closes": sparks,
                }
            )
        return {"subnets": rows}
    except Exception as exc:
        logger.error("Error fetching indicators convergence: %s", exc)
        return {"subnets": [], "error": str(exc)}


@indicators_router.get("/api/indicators/scheduler")
async def api_indicators_scheduler():
    """Return the current state of the background indicator scheduler."""
    return {
        "status": "success",
        "data": get_indicator_scheduler_state(),
    }
