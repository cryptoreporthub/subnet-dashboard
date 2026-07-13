"""Agent A (slice 12a) — learning/council/freshness context for ``GET /``."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from datastore.learning_engine import LearningEngine
from internal.council import pick_history, rotation_tracker, scenario_memory
from internal.council.weights import load_weights
from internal.learning.predictions_store import load_predictions, update_stats

logger = logging.getLogger(__name__)


def _mindmap_trail_panel() -> List[Dict[str, Any]]:
    try:
        from internal.learning.mindmap_aggregator import collect_trail_events

        return collect_trail_events(limit=50)
    except Exception as exc:
        logger.warning("mindmap trail panel failed: %s", exc)
        return []


def default_learning_dashboard_context() -> Dict[str, Any]:
    """Safe fallbacks when learning/council sections fail to load."""
    return {
        "mindmap": {},
        "learning_stats": {},
        "learning_metrics": {
            "expert_weights": {},
            "total_records": 0,
            "predictions_pending": 0,
            "predictions_resolved": 0,
            "correct": 0,
            "wrong": 0,
            "accuracy": 0.0,
            "deltas": {"correct": 0.02, "wrong": -0.03},
            "recent_resolutions": [],
            "last_updated": None,
        },
        "expert_weights": {},
        "council_weights": [],
        "predictions": [],
        "patterns": [],
        "mindmap_trail": [],
        "hour_picks": [],
        "day_picks": [],
        "daily_pick": {},
        "rotation_tracker": {
            "patterns": [],
            "volatility_clusters": {"summary": {"mean_volatility": 0.0}},
        },
        "scenario_memory": {
            "status": "ok",
            "scenarios": [],
            "regimes": {},
            "stats": {"total": 0, "by_regime": {}},
            "meta": {},
        },
        "pick_history": {
            "active": None,
            "history": [],
            "stats": {"total": 0, "wins": 0, "losses": 0, "success_rate": 0.0},
        },
        "freshness": {"last_updated": {}, "now": None},
    }


def _mindmap_summary() -> Dict[str, Any]:
    engine = LearningEngine()
    stats = engine.get_stats()
    expert_weights = stats.get("expert_weights", {})
    try:
        from internal.council import resolver

        resolved = resolver.get_resolved_predictions()
    except Exception:
        resolved = {"stats": {}}

    try:
        from server import _safe_simivision_payload

        simivision = _safe_simivision_payload()["data"]
    except Exception as exc:
        logger.warning("SimiVision snapshot unavailable for mindmap: %s", exc)
        simivision = {"meta": {"count": 0}}

    rot = {}
    try:
        from fetchers.taomarketcap import get_all_subnets

        rot = rotation_tracker.get_rotation_summary(get_all_subnets() or [])
    except Exception:
        rot = {"patterns": [], "volatility_clusters": {}}

    scen = {}
    try:
        scen = scenario_memory.get_memory_snapshot()
    except Exception:
        scen = {"scenarios": [], "meta": {}}

    return {
        "acknowledgment": "Dashboard data ready",
        "expert_weights": expert_weights,
        "resolved_predictions": {
            "total": resolved.get("stats", {}).get("total", 0),
            "correct": resolved.get("stats", {}).get("correct", 0),
            "wrong": resolved.get("stats", {}).get("wrong", 0),
            "pending": resolved.get("stats", {}).get("pending", 0),
            "accuracy": resolved.get("stats", {}).get("accuracy", 0.0),
        },
        "scenario_memory": {
            "scenario_count": len(scen.get("scenarios", [])),
            "last_scenario": (scen.get("scenarios") or [{}])[-1].get("name")
            if scen.get("scenarios")
            else None,
            "last_updated": scen.get("meta", {}).get("last_updated"),
        },
        "rotation_tracker": rot,
        "learning_status": {
            "enabled": True,
            "records": stats.get("total_records", 0),
            "last_updated": stats.get("last_updated")
            or simivision.get("meta", {}).get("updated_at"),
        },
    }


def _learning_stats() -> Dict[str, Any]:
    stats = LearningEngine().get_stats()
    return {
        "expert_weights": stats.get("expert_weights", {}),
        "total_records": stats.get("total_records", 0),
        "accuracy": stats.get("accuracy", 0.0),
        "pending": stats.get("pending", 0),
        "resolved": stats.get("resolved", 0),
        "last_updated": stats.get("last_updated"),
    }


def _learning_metrics() -> Dict[str, Any]:
    try:
        from internal.learning.routes import _compute_learning_metrics

        return _compute_learning_metrics()
    except Exception as exc:
        logger.warning("learning metrics failed: %s", exc)
        return default_learning_dashboard_context()["learning_metrics"]


def _council_weights_list(weights: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        {"expert": name, "weight": float(value), "bias": 0.0}
        for name, value in (weights or {}).items()
    ]


def _predictions_panel() -> List[Dict[str, Any]]:
    try:
        data = load_predictions()
        update_stats(data)
        return list(data.get("predictions", []))[:12]
    except Exception as exc:
        logger.warning("predictions panel failed: %s", exc)
        return []


def _pick_sections(
    subnets: List[Dict[str, Any]], market_context: Dict[str, Any]
) -> Dict[str, Any]:
    hour_picks: List[Dict[str, Any]] = []
    day_picks: List[Dict[str, Any]] = []
    daily_pick: Dict[str, Any] = {}
    try:
        from internal.council.daily_pick_engine import get_or_create_today_pick
        from server import _ordered_hour_picks

        hour_picks = _ordered_hour_picks(subnets, market_context, limit=3)
        raw = get_or_create_today_pick(subnets, market_context)
        daily_pick = raw.get("pick") if isinstance(raw, dict) and raw.get("pick") else raw
        if not isinstance(daily_pick, dict):
            daily_pick = {}
        pick_data = raw.get("pick") if isinstance(raw, dict) else None
        if pick_data and isinstance(pick_data, dict) and pick_data.get("subnet"):
            candidate = pick_data["subnet"]
            sn = next(
                (s for s in subnets if s.get("netuid") == candidate.get("netuid")),
                {},
            )
            day_picks.append(
                {
                    "netuid": candidate.get("netuid"),
                    "name": candidate.get("name"),
                    "symbol": candidate.get("symbol"),
                    "score": pick_data.get("score", 0.0),
                    "confidence": pick_data.get("confidence", 0.0),
                    "signals": {
                        "price_change_24h": sn.get("price_change_24h"),
                        "price_change_7d": sn.get("price_change_7d"),
                        "emission": sn.get("emission"),
                        "apy": sn.get("apy"),
                        "volume": sn.get("volume"),
                    },
                    "scenario_tags": pick_data.get("scenario_tags", {}),
                }
            )
    except Exception as exc:
        logger.warning("pick sections failed: %s", exc)
    return {
        "hour_picks": hour_picks,
        "day_picks": day_picks,
        "daily_pick": daily_pick if isinstance(daily_pick, dict) else {},
    }


def _rotation_panel(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        summary = rotation_tracker.get_rotation_summary(subnets)
        return {"status": "ok", **summary}
    except Exception as exc:
        logger.warning("rotation tracker panel failed: %s", exc)
        return default_learning_dashboard_context()["rotation_tracker"]


def _scenario_panel() -> Dict[str, Any]:
    try:
        return {"status": "ok", **scenario_memory.get_memory_snapshot()}
    except Exception as exc:
        logger.warning("scenario memory panel failed: %s", exc)
        return default_learning_dashboard_context()["scenario_memory"]


def _freshness_panel() -> Dict[str, Any]:
    try:
        from internal import freshness_tracker

        return freshness_tracker.snapshot()
    except Exception as exc:
        logger.warning("freshness panel failed: %s", exc)
        return {"last_updated": {}, "now": None}


def _mark_learning_freshness() -> None:
    try:
        from internal import freshness_tracker

        for key in (
            "predictions",
            "top_pick_hour",
            "top_pick_day",
            "rotation",
            "scenario_memory",
        ):
            freshness_tracker.mark_updated(key)
    except Exception:
        pass


def build_learning_dashboard_context(
    subnets: Optional[List[Dict[str, Any]]] = None,
    market_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compose Agent A's server-rendered dashboard keys for ``GET /``."""
    subnets = subnets if isinstance(subnets, list) else []
    market_context = market_context if isinstance(market_context, dict) else {"tao_change_24h": 0.0}

    weights = load_weights()
    expert_weights = _learning_stats().get("expert_weights", weights)
    picks = _pick_sections(subnets, market_context)
    rotation = _rotation_panel(subnets)

    ctx = default_learning_dashboard_context()
    ctx.update(
        {
            "mindmap": _mindmap_summary(),
            "learning_stats": _learning_stats(),
            "learning_metrics": _learning_metrics(),
            "expert_weights": expert_weights,
            "council_weights": _council_weights_list(weights),
            "predictions": _predictions_panel(),
            "patterns": rotation.get("patterns", []),
            "hour_picks": picks["hour_picks"],
            "day_picks": picks["day_picks"],
            "daily_pick": picks["daily_pick"],
            "rotation_tracker": rotation,
            "scenario_memory": _scenario_panel(),
            "pick_history": pick_history.get_history(limit=20),
            "freshness": _freshness_panel(),
            "mindmap_trail": _mindmap_trail_panel(),
        }
    )
    _mark_learning_freshness()
    return ctx
