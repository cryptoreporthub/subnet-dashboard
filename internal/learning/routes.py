"""FastAPI read routes for the learning loop (slice 5)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Query

from datastore.learning_engine import LearningEngine
from internal.council import resolver, rotation_tracker, scenario_memory
from internal.council.resolver_scheduler import get_prediction_resolver_scheduler_state
from internal.learning.predictions_store import load_predictions, save_predictions, update_stats

logger = logging.getLogger(__name__)

learning_router = APIRouter(tags=["learning"])

_LEARNING_DELTA_CORRECT = 0.02
_LEARNING_DELTA_WRONG = -0.03


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _scenario_memory_summary() -> Dict[str, Any]:
    try:
        data = scenario_memory._load()
        scenarios = data.get("scenarios", [])
        return {
            "scenario_count": len(scenarios),
            "last_scenario": scenarios[-1].get("name") if scenarios else None,
            "last_updated": data.get("meta", {}).get("last_updated"),
        }
    except Exception as exc:
        logger.warning("Could not load scenario memory summary: %s", exc)
        return {"scenario_count": 0, "last_scenario": None, "last_updated": None}


def _rotation_summary() -> Dict[str, Any]:
    try:
        from fetchers.taomarketcap import get_all_subnets

        subnets = get_all_subnets() or []
        return rotation_tracker.get_rotation_summary(subnets)
    except Exception as exc:
        logger.warning("Could not load rotation tracker summary: %s", exc)
        return {
            "timestamp": _utcnow_z(),
            "patterns": [],
            "volatility_clusters": {},
        }


def _compute_learning_metrics() -> Dict[str, Any]:
    engine = LearningEngine()
    stats = engine.get_stats()
    resolved = resolver.get_resolved_predictions()
    recent = resolved.get("resolved", [])[-10:]
    return {
        "expert_weights": stats.get("expert_weights", {}),
        "total_records": stats.get("total_records", 0),
        "predictions_pending": stats.get("pending", 0),
        "predictions_resolved": stats.get("resolved", 0),
        "correct": resolved.get("stats", {}).get("correct", 0),
        "wrong": resolved.get("stats", {}).get("wrong", 0),
        "accuracy": stats.get("accuracy", 0.0),
        "deltas": {"correct": _LEARNING_DELTA_CORRECT, "wrong": _LEARNING_DELTA_WRONG},
        "recent_resolutions": [
            {
                "name": row.get("name"),
                "predicted_pct": row.get("predicted_pct"),
                "actual_pct": row.get("actual_pct"),
                "correct": row.get("correct"),
                "statement": row.get("statement"),
            }
            for row in recent
        ],
        "last_updated": stats.get("last_updated"),
    }


@learning_router.get("/api/mindmap/summary")
async def api_mindmap_summary():
    """Mindmap summary wired to expert weights and resolver stats."""
    try:
        from server import _safe_simivision_payload

        simivision = _safe_simivision_payload()["data"]
    except Exception as exc:
        logger.warning("SimiVision snapshot unavailable for mindmap: %s", exc)
        simivision = {"meta": {"count": 0, "updated_at": _utcnow_z()}}

    engine = LearningEngine()
    stats = engine.get_stats()
    expert_weights = stats.get("expert_weights", {})
    resolved = resolver.get_resolved_predictions()
    return {
        "status": "success",
        "data": {
            "acknowledgment": "Dashboard data ready",
            "noticed": ["Using safe cached subnet snapshot"],
            "opinion_changes": ["No significant opinion changes"],
            "technical_indicators": ["No strong technical signals"],
            "conviction": {
                "current": 50.0,
                "trend": "stable",
                "explanation": f"Derived from {simivision.get('meta', {}).get('count', 0)} subnets",
            },
            "expert_insights": [
                {"expert": name.title(), "weight": weight}
                for name, weight in expert_weights.items()
            ],
            "expert_weights": expert_weights,
            "resolved_predictions": {
                "total": resolved.get("stats", {}).get("total", 0),
                "correct": resolved.get("stats", {}).get("correct", 0),
                "wrong": resolved.get("stats", {}).get("wrong", 0),
                "pending": resolved.get("stats", {}).get("pending", 0),
                "accuracy": resolved.get("stats", {}).get("accuracy", 0.0),
            },
            "scenario_memory": _scenario_memory_summary(),
            "rotation_tracker": _rotation_summary(),
            "learning_status": {
                "enabled": True,
                "records": stats.get("total_records", 0),
                "last_updated": stats.get("last_updated")
                or simivision.get("meta", {}).get("updated_at"),
            },
        },
    }


@learning_router.get("/api/learning/stats")
async def api_learning_stats():
    engine = LearningEngine()
    stats = engine.get_stats()
    return {
        "status": "success",
        "data": {
            "expert_weights": stats.get("expert_weights", {}),
            "total_records": stats.get("total_records", 0),
            "accuracy": stats.get("accuracy", 0.0),
            "pending": stats.get("pending", 0),
            "resolved": stats.get("resolved", 0),
            "last_updated": stats.get("last_updated") or _utcnow_z(),
        },
    }


@learning_router.get("/api/learning-metrics")
async def api_learning_metrics():
    try:
        return _compute_learning_metrics()
    except Exception as exc:
        logger.error("Error fetching learning metrics: %s", exc)
        return {"error": str(exc), "expert_weights": {}, "accuracy": 0.0}


@learning_router.get("/api/predictions")
async def api_predictions():
    try:
        data = load_predictions()
        update_stats(data)
        save_predictions(data)
        return {
            "predictions": data.get("predictions", []),
            "resolved": data.get("resolved", []),
            "stats": data.get("stats", {}),
        }
    except Exception as exc:
        logger.error("Error fetching predictions: %s", exc)
        return {"predictions": [], "resolved": [], "stats": {}, "error": str(exc)}


@learning_router.get("/api/predictions/resolved")
async def api_predictions_resolved(resolve: bool = Query(default=False)):
    """Return resolved predictions. Read-only unless ``resolve=true``."""
    try:
        if resolve:
            from fetchers.taomarketcap import get_all_subnets

            subnets = get_all_subnets() or []
            result = resolver.resolve_due_predictions(subnets)
        else:
            result = resolver.get_resolved_predictions()
        return {
            "status": "ok",
            "resolved": result.get("resolved", []),
            "stats": result.get("stats", {}),
            "triggered_resolution": resolve,
        }
    except Exception as exc:
        logger.error("Error resolving predictions: %s", exc)
        return {"status": "error", "resolved": [], "stats": {}, "error": str(exc)}


@learning_router.get("/api/predictions/resolver")
async def api_predictions_resolver_state():
    return {
        "status": "success",
        "data": get_prediction_resolver_scheduler_state(),
    }
