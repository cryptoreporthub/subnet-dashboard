"""FastAPI read routes for the technical indicator layer (slice 7)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter

from internal.indicators.convergence import build_indicators_convergence

logger = logging.getLogger(__name__)

indicators_router = APIRouter(tags=["indicators"])


@indicators_router.get("/api/indicators-convergence")
async def api_indicators_convergence():
    """Return multi-indicator oversold/overbought convergence for top subnets."""
    try:
        from server import _get_subnets_with_source

        subnets, _ = _get_subnets_with_source()
        return build_indicators_convergence(subnets)
    except Exception as exc:
        logger.error("Error fetching indicators convergence: %s", exc)
        return {"subnets": [], "error": str(exc)}