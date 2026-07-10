"""Agent B root-page context for GET / (slice 12b).

Composes pump, whale, ruggers, indicator, oracle, and price-tracking
snapshots from owned modules. Safe defaults on any partial failure.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PRICE_BASELINE_FILE = os.environ.get("PRICE_BASELINE_FILE", "data/price_baselines.json")


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _empty_pump_analytics() -> Dict[str, Any]:
    return {
        "status": "success",
        "data": {
            "subnets": [],
            "meta": {
                "tracked_subnets": 0,
                "total_cycles": 0,
                "avg_proneness": 0.0,
                "top_pump_candidates": [],
                "updated_at": _utcnow_z(),
            },
        },
    }


def _safe_pump_analytics() -> Dict[str, Any]:
    try:
        from internal.pump_tracker import get_pump_tracker

        tracker = get_pump_tracker()
        if tracker is None:
            return _empty_pump_analytics()
        return tracker.get_all_analytics()
    except Exception as exc:
        logger.warning("Could not load pump analytics for root: %s", exc)
        return _empty_pump_analytics()


def _safe_indicators_convergence(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        from internal.council.state_vector import (
            _compute_technical_indicators,
            _detect_overbought_convergence,
            _detect_oversold_convergence,
        )

        ranked = sorted(
            subnets,
            key=lambda s: (s.get("emission", 0), s.get("apy", 0), s.get("volume", 0)),
            reverse=True,
        )
        rows = []
        for sn in ranked[:6]:
            indicators = _compute_technical_indicators(sn)
            rows.append(
                {
                    "netuid": sn.get("netuid"),
                    "name": sn.get("name"),
                    "oversold": _detect_oversold_convergence(indicators),
                    "overbought": _detect_overbought_convergence(indicators),
                }
            )
        return {"subnets": rows}
    except Exception as exc:
        logger.warning("Could not load indicators convergence for root: %s", exc)
        return {"subnets": [], "error": str(exc)}


def _safe_indicator_state() -> Dict[str, Any]:
    try:
        from internal.indicators.indicator_engine import IndicatorEngine

        return IndicatorEngine().get_indicator_state()
    except Exception as exc:
        logger.warning("Could not load indicator state for root: %s", exc)
        return {}


def _safe_whale_summary() -> Dict[str, Any]:
    try:
        from internal.whales.service import WhaleIntelligenceService

        return WhaleIntelligenceService().summary()
    except Exception as exc:
        logger.warning("Could not load whale summary for root: %s", exc)
        return {"status": "error", "error": str(exc)}


def _safe_ruggers_summary() -> Dict[str, Any]:
    try:
        from internal.ruggers.watchlist import RuggerWatchlist

        return RuggerWatchlist().summary()
    except Exception as exc:
        logger.warning("Could not load ruggers summary for root: %s", exc)
        return {"status": "error", "error": str(exc)}


def _safe_oracle_snapshot(subnets: List[Dict[str, Any]], source: str) -> Dict[str, Any]:
    try:
        snapshot = [
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
        logger.warning("Could not build oracle snapshot for root: %s", exc)
        return {"status": "stub", "source": "error", "data": [], "error": str(exc)}


def _safe_price_baselines() -> Dict[str, Any]:
    try:
        if not os.path.exists(PRICE_BASELINE_FILE):
            return {
                "status": "success",
                "meta": {"count": 0, "source": "file"},
                "baselines": [],
            }
        with open(PRICE_BASELINE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            data = []
        netuids = {e.get("netuid") for e in data if e.get("netuid") is not None}
        return {
            "status": "success",
            "meta": {
                "count": len(data),
                "tracked_subnets": len(netuids),
                "source": "file",
            },
            "baselines": data,
        }
    except Exception as exc:
        logger.warning("Could not load price baselines for root: %s", exc)
        return {"status": "error", "error": str(exc), "baselines": []}


def build_agent_b_root_context(
    subnets: Optional[List[Dict[str, Any]]] = None,
    data_source: str = "unknown",
) -> Dict[str, Any]:
    """Return template keys owned by Agent B for the homepage."""
    subnets = subnets if isinstance(subnets, list) else []
    return {
        "pump_analytics": _safe_pump_analytics(),
        "api_indicators_convergence": _safe_indicators_convergence(subnets),
        "indicator_state": _safe_indicator_state(),
        "whale_intelligence": _safe_whale_summary(),
        "ruggers_watchlist": _safe_ruggers_summary(),
        "oracle_snapshot": _safe_oracle_snapshot(subnets, data_source),
        "price_tracking_baselines": _safe_price_baselines(),
    }
