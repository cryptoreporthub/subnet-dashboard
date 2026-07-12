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

from internal.analytics.phase_b_hooks import refresh_agent_b_trails
from internal.analytics.pump_summary import summarize_pump
from internal.analytics.scenario_state import load_scenario_snapshot
from internal.analytics.scenario_summary import summarize_scenario

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
    pump_analytics = _safe_pump_analytics()
    scenario_snapshot = load_scenario_snapshot()
    refresh_agent_b_trails(pump_payload=pump_analytics, scenario_snapshot=scenario_snapshot)
    ctx = {
        "pump_analytics": pump_analytics,
        "pump_summary": summarize_pump(pump_analytics),
        "scenario_summary": summarize_scenario(scenario_snapshot),
        "api_indicators_convergence": _safe_indicators_convergence(subnets),
        "indicator_state": _safe_indicator_state(),
        "whale_intelligence": _safe_whale_summary(),
        "ruggers_watchlist": _safe_ruggers_summary(),
        "oracle_snapshot": _safe_oracle_snapshot(subnets, data_source),
        "price_tracking_baselines": _safe_price_baselines(),
    }
    try:
        from internal.learning.premium_dashboard_builders import (
            build_signal_impact,
            build_simivision_picks,
            build_social_sentiment,
            build_technical_indicators,
            build_undervalued_radar,
        )

        ctx.update(
            {
                "simivision_picks": build_simivision_picks(subnets),
                "undervalued_radar": build_undervalued_radar(subnets),
                "technical_indicators": build_technical_indicators(subnets),
                "signal_impact": build_signal_impact(subnets),
                "social_sentiment": build_social_sentiment(subnets),
                "market_intelligence": build_market_intelligence(subnets),
                "staking_analytics": build_staking_analytics(subnets),
            }
        )
    except Exception as exc:
        logger.warning("H-full premium context failed for root: %s", exc)
        ctx.update(
            {
                "simivision_picks": [],
                "undervalued_radar": [],
                "technical_indicators": [],
                "signal_impact": [],
                "social_sentiment": [],
                "market_intelligence": build_market_intelligence(subnets),
                "staking_analytics": build_staking_analytics(subnets),
            }
        )
    return ctx


def build_market_intelligence(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Market scanner summary (premium-dashboard-redesign §4)."""
    rows = [s for s in subnets if isinstance(s, dict)]
    if not rows:
        return {
            "total": 0,
            "avg_change_24h": 0.0,
            "gainers": 0,
            "losers": 0,
            "top_gainer": {},
            "top_loser": {},
            "avg_apy": 0.0,
            "total_volume": 0.0,
            "total_market_cap": 0.0,
            "breadth": "neutral",
        }

    changes = [float(s.get("price_change_24h", 0) or 0) for s in rows]
    gainers = sum(1 for c in changes if c > 0)
    losers = sum(1 for c in changes if c < 0)
    sorted_by_change = sorted(rows, key=lambda s: float(s.get("price_change_24h", 0) or 0))
    top_loser_row = sorted_by_change[0]
    top_gainer_row = sorted_by_change[-1]

    def _mini(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": row.get("name"),
            "netuid": row.get("netuid"),
            "change": round(float(row.get("price_change_24h", 0) or 0), 2),
        }

    ratio = gainers / max(gainers + losers, 1)
    if ratio >= 0.55:
        breadth = "bullish"
    elif ratio <= 0.45:
        breadth = "bearish"
    else:
        breadth = "neutral"

    return {
        "total": len(rows),
        "avg_change_24h": round(sum(changes) / len(changes), 2),
        "gainers": gainers,
        "losers": losers,
        "top_gainer": _mini(top_gainer_row),
        "top_loser": _mini(top_loser_row),
        "avg_apy": round(
            sum(float(s.get("apy", 0) or 0) for s in rows) / len(rows),
            2,
        ),
        "total_volume": round(sum(float(s.get("volume", 0) or 0) for s in rows), 2),
        "total_market_cap": round(sum(float(s.get("market_cap", 0) or 0) for s in rows), 2),
        "breadth": breadth,
    }


def build_staking_analytics(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Staking & yield summary (premium-dashboard-redesign §5)."""
    rows = [s for s in subnets if isinstance(s, dict)]
    if not rows:
        return {
            "top_yield": [],
            "total_stake": 0.0,
            "avg_apy": 0.0,
            "subnet_count": 0,
        }

    ranked = sorted(rows, key=lambda s: float(s.get("apy", 0) or 0), reverse=True)
    top_yield: List[Dict[str, Any]] = []
    for sn in ranked[:10]:
        apy = float(sn.get("apy", 0) or 0)
        emission = float(sn.get("emission", 0) or 0)
        volume = float(sn.get("volume", 0) or 0)
        top_yield.append(
            {
                "netuid": sn.get("netuid"),
                "name": sn.get("name"),
                "apy": round(apy, 2),
                "emission": round(emission, 4),
                "total_stake": round(volume * 0.1, 2),
                "tao_liquidity": round(volume * 0.05, 2),
                "alpha_liquidity": round(volume * 0.05, 2),
                "yield_score": round(min(100.0, apy * 1.5 + emission * 5), 2),
            }
        )

    return {
        "top_yield": top_yield,
        "total_stake": round(sum(float(s.get("volume", 0) or 0) for s in rows) * 0.1, 2),
        "avg_apy": round(sum(float(s.get("apy", 0) or 0) for s in rows) / len(rows), 2),
        "subnet_count": len(rows),
    }
