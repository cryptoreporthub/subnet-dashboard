"""FastAPI read routes for pump analytics and price tracking (slice 10b)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from internal.analytics.backtest import run_backtest
from internal.analytics.market_drivers import (
    build_driver_card_for_netuid,
    learned_price_drivers,
)
from internal.analytics.phase_b_hooks import refresh_agent_b_trails
from internal.analytics.pump_summary import summarize_pump
from internal.analytics.report import build_subnet_report
from internal.analytics.scenario_state import load_scenario_snapshot
from internal.analytics.scenario_summary import summarize_scenario

logger = logging.getLogger(__name__)

analytics_router = APIRouter(tags=["analytics"])

PRICE_BASELINE_FILE = os.environ.get("PRICE_BASELINE_FILE", "data/price_baselines.json")


def _empty_pump_payload() -> Dict[str, Any]:
    return {
        "status": "error",
        "data": {
            "subnets": [],
            "meta": {
                "tracked_subnets": 0,
                "total_cycles": 0,
                "avg_proneness": 0.0,
                "top_pump_candidates": [],
                "updated_at": None,
            },
        },
    }


@analytics_router.get("/api/pump-analytics")
async def api_pump_analytics(netuid: Optional[int] = Query(default=None)):
    """Return pump cycle analytics for all subnets or one via ``?netuid=``."""
    try:
        from internal.pump_tracker import get_pump_tracker

        tracker = get_pump_tracker()
        if tracker is None:
            payload = _empty_pump_payload()
            payload["summary"] = summarize_pump(payload)
            return payload
        data = tracker.get_all_analytics()
        scenario_snapshot = load_scenario_snapshot()
        refresh_agent_b_trails(pump_payload=data, scenario_snapshot=scenario_snapshot)
        try:
            from internal.pump.scheduler import ensure_pump_ladder_scheduler

            ensure_pump_ladder_scheduler(immediate=False)
        except ImportError:
            pass
        data["summary"] = summarize_pump(data)
        data["scenario_summary"] = summarize_scenario(scenario_snapshot)
        if netuid is not None:
            subnets = [
                s for s in data["data"]["subnets"] if s.get("netuid") == netuid
            ]
            data["data"]["subnets"] = subnets
            data["data"]["meta"]["tracked_subnets"] = len(subnets)
        return data
    except Exception as exc:
        logger.warning("pump-analytics failed: %s", exc)
        payload = _empty_pump_payload()
        payload["error"] = str(exc)
        payload["summary"] = summarize_pump(payload)
        return payload


@analytics_router.get("/api/price-tracking/baselines")
async def api_price_tracking_baselines():
    """Return recorded baseline price history for tracked subnets."""
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
        logger.warning("price-tracking/baselines failed: %s", exc)
        return {"status": "error", "error": str(exc), "baselines": []}


@analytics_router.get("/api/price-tracking/outcomes")
async def api_price_tracking_outcomes():
    """Return recorded price outcomes (empty when message-intel DB unavailable)."""
    try:
        from message_intel.models import MessageIntelDB

        db = MessageIntelDB()
        outcomes: List[Dict[str, Any]] = db.list_price_outcomes(limit=100)
        return {
            "status": "success",
            "meta": {"count": len(outcomes)},
            "outcomes": outcomes,
        }
    except Exception as exc:
        logger.warning("price-tracking/outcomes unavailable: %s", exc)
        return {"status": "success", "meta": {"count": 0}, "outcomes": []}


@analytics_router.get("/api/backtest")
async def api_backtest(limit: int = Query(default=200, ge=1, le=500)):
    """Replay resolved predictions — Oracle / Echo / Pulse win-rate + calibration."""
    try:
        return run_backtest(limit=limit)
    except Exception as exc:
        logger.warning("backtest failed: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "sample_size": 0,
            "council": {"wins": 0, "losses": 0, "win_rate": None},
            "judges": {},
            "history": [],
        }


@analytics_router.get("/api/market-drivers")
async def api_market_drivers():
    """What predicted token price moves — learned from resolved predictions + scenarios."""
    try:
        return {"status": "success", **learned_price_drivers()}
    except Exception as exc:
        logger.warning("market-drivers failed: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "ready": False,
            "top_price_signals": [],
            "top_scenario_tags": [],
        }


@analytics_router.get("/api/market-drivers/{netuid}")
async def api_market_drivers_subnet(netuid: int):
    """Per-subnet driver card: price vs staking yield, grade, learned context."""
    try:
        payload = build_driver_card_for_netuid(netuid)
        return payload
    except Exception as exc:
        logger.warning("market-drivers SN%s failed: %s", netuid, exc)
        return {"status": "error", "netuid": netuid, "error": str(exc)}


@analytics_router.get("/api/report/{netuid}")
async def api_subnet_report(netuid: int):
    """Exportable per-subnet analysis (markdown + structured sections)."""
    try:
        return build_subnet_report(netuid)
    except Exception as exc:
        logger.warning("subnet report failed for SN%s: %s", netuid, exc)
        return {
            "status": "error",
            "netuid": netuid,
            "error": str(exc),
            "markdown": f"# Subnet SN{netuid}\n\nReport generation failed.",
            "sections": {},
        }


try:
    from internal.trace.routes import trace_router

    analytics_router.include_router(trace_router)
except Exception as _trace_exc:  # pragma: no cover - defensive import guard
    logger.warning("Trace lineage routes unavailable: %s", _trace_exc)

try:
    from internal.pump.routes import pump_ladder_router

    analytics_router.include_router(pump_ladder_router)
except ImportError as _pump_exc:
    logger.warning("Pump ladder routes unavailable: %s", _pump_exc)
