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

logger = logging.getLogger(__name__)

indicators_router = APIRouter(tags=["indicators"])


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
            degraded = bool(indicators.get("degraded"))
            hist = _get_price_history(sn.get("netuid"), sn)
            sparks = hist.get("closes") or []
            if hist.get("source") in ("synthetic", "unavailable") or len(sparks) < 2:
                sparks = []
            else:
                sparks = [float(c) for c in sparks[-24:]]
            row: Dict[str, Any] = {
                "netuid": sn.get("netuid"),
                "name": sn.get("name"),
                "degraded": degraded,
                "spark_closes": sparks,
            }
            if degraded:
                row["reason"] = indicators.get("history_source", "no_ohlcv")
                row["oversold"] = {"convergent": False, "count": 0, "reason": "no_ohlcv"}
                row["overbought"] = {"convergent": False, "count": 0, "reason": "no_ohlcv"}
            else:
                row["oversold"] = _detect_oversold_convergence(indicators)
                row["overbought"] = _detect_overbought_convergence(indicators)
            rows.append(row)
        has_real = any(not r.get("degraded") for r in rows)
        return {
            "data_available": has_real,
            "source": "state_vector" if has_real else "none",
            "reason": None if has_real else "no_ohlcv",
            "subnets": rows,
        }
    except Exception as exc:
        logger.error("Error fetching indicators convergence: %s", exc)
        return {"subnets": [], "error": str(exc)}