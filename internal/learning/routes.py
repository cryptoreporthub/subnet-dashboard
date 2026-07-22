"""FastAPI routes for the learning loop (slices 5–11)."""

from __future__ import annotations

import html
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response

from datastore.learning_engine import LearningEngine, create_feedback_router
from internal.council import pick_history, resolver, rotation_tracker, scenario_memory
from internal.council.watchdog import check_resolver_watchdog
from internal.council.weights import load_impact_strength, load_weights
from internal.council.resolver_scheduler import (
    get_prediction_resolver_scheduler,
    get_prediction_resolver_scheduler_state,
    start_prediction_resolver_scheduler,
)
from internal.learning.predictions_store import load_predictions, save_predictions, update_stats

logger = logging.getLogger(__name__)

learning_router = APIRouter(tags=["learning"])
learning_router.include_router(create_feedback_router())

_LEARNING_DELTA_CORRECT = 0.02
_LEARNING_DELTA_WRONG = -0.03
_LEARNING_SNAPSHOT_TTL = 30.0
_learning_snapshot_lock = threading.Lock()
_learning_snapshot_cache: Dict[str, Any] = {"at": 0.0, "data": None}


def _learning_snapshot() -> Dict[str, Any]:
    """Shared ≤30s snapshot for stats / metrics / mindmap (§31-3 O20)."""
    now = time.time()
    with _learning_snapshot_lock:
        if now - float(_learning_snapshot_cache.get("at") or 0) < _LEARNING_SNAPSHOT_TTL:
            cached = _learning_snapshot_cache.get("data")
            if isinstance(cached, dict):
                return cached

    engine = LearningEngine()
    stats = engine.get_stats()
    resolved_payload = resolver.get_resolved_predictions()
    resolver_stats = resolved_payload.get("stats", {})
    pending_rows = load_predictions().get("predictions", []) or []
    watchdog = check_resolver_watchdog(pending_rows)
    from internal.learning.trust_stats import build_trust_banner

    trust_banner = build_trust_banner(resolver_stats, watchdog=watchdog)
    recent = resolved_payload.get("resolved", [])[-10:]
    snapshot = {
        "engine_stats": stats,
        "resolver_stats": resolver_stats,
        "resolved_payload": resolved_payload,
        "pending_rows": pending_rows,
        "watchdog": watchdog,
        "trust_banner": trust_banner,
        "recent": recent,
        "scenario": _scenario_memory_summary(),
        "expert_weights": stats.get("expert_weights", {}),
    }
    with _learning_snapshot_lock:
        _learning_snapshot_cache["at"] = now
        _learning_snapshot_cache["data"] = snapshot
    return snapshot


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _subnets_for_tracker() -> list:
    try:
        from internal.subnets.feed import load_pick_subnets

        return load_pick_subnets()
    except Exception as exc:
        logger.warning("Subnet list for council trackers failed: %s", exc)
        return []


def _scenario_memory_summary() -> Dict[str, Any]:
    try:
        from internal.learning.scenario_outcomes import scenario_outcome_stats

        return scenario_outcome_stats()
    except Exception as exc:
        logger.warning("Could not load scenario memory summary: %s", exc)
        return {
            "scenario_count": 0,
            "outcomes_resolved": 0,
            "outcomes_pending": 0,
            "last_scenario": None,
            "last_outcome": None,
            "last_updated": None,
        }


def _rotation_summary() -> Dict[str, Any]:
    try:
        return rotation_tracker.get_rotation_summary(_subnets_for_tracker())
    except Exception as exc:
        logger.warning("Could not load rotation tracker summary: %s", exc)
        return {
            "timestamp": _utcnow_z(),
            "patterns": [],
            "volatility_clusters": {},
        }


def _compute_learning_metrics() -> Dict[str, Any]:
    from internal.learning.weight_deltas import recent_expert_weight_deltas

    snap = _learning_snapshot()
    stats = snap["engine_stats"]
    resolver_stats = snap["resolver_stats"]
    watchdog = snap["watchdog"]
    trust_banner = snap["trust_banner"]
    recent = snap["recent"]
    return {
        "expert_weights": stats.get("expert_weights", {}),
        "expert_weight_deltas": recent_expert_weight_deltas(),
        "total_records": stats.get("total_records", 0),
        "predictions_pending": stats.get("pending", 0),
        "predictions_resolved": stats.get("resolved", 0),
        "correct": resolver_stats.get("correct", 0),
        "wrong": resolver_stats.get("wrong", 0),
        "accuracy": resolver_stats.get("accuracy", stats.get("accuracy", 0.0)),
        "expired": resolver_stats.get("expired", 0),
        "expired_rate": trust_banner.get("expired_rate"),
        "graded": trust_banner.get("graded"),
        "trust_banner": trust_banner,
        "watchdog": watchdog,
        "brain_ui_ready": trust_banner.get("ready"),
        "deltas": {"correct": _LEARNING_DELTA_CORRECT, "wrong": _LEARNING_DELTA_WRONG},
        "impact_strength": {
            "value": load_impact_strength(),
            "range": [0.0, 2.0],
            "default": 1.0,
            "env_override": "IMPACT_STRENGTH",
            "meaning": "0=no size tilt, 1=default, 2=aggressive small-cap bias; SimiVision nudges ±0.02 on resolve",
        },
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
        from server import _market_context_with_weights, _safe_simivision_payload

        simivision = _safe_simivision_payload()["data"]
    except Exception as exc:
        logger.warning("SimiVision snapshot unavailable for mindmap: %s", exc)
        simivision = {"meta": {"count": 0, "updated_at": _utcnow_z()}}

    snap = _learning_snapshot()
    stats = snap["engine_stats"]
    expert_weights = snap["expert_weights"]
    resolved = snap["resolved_payload"]

    dpick_block: Dict[str, Any] = {"shortlist": []}
    try:
        from internal.council.daily_pick_engine import get_or_create_today_pick
        from internal.learning.dpick_shortlist import (
            build_deliberation_shortlist,
            shortlist_cards_for_template,
        )

        subnets = _subnets_for_tracker()
        market_context = _market_context_with_weights(subnets)
        daily_payload = get_or_create_today_pick(subnets, market_context)
        deliberation = build_deliberation_shortlist(subnets, market_context, daily_payload)
        cards = shortlist_cards_for_template(deliberation)
        dpick_block = {"shortlist": cards if len(cards) >= 2 else []}
    except Exception as exc:
        logger.warning("mindmap summary dpick.shortlist failed: %s", exc)
        dpick_block = {"shortlist": []}

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
            "scenario_memory": snap["scenario"],
            "rotation_tracker": _rotation_summary(),
            "learning_status": {
                "enabled": True,
                "records": stats.get("total_records", 0),
                "last_updated": stats.get("last_updated")
                or simivision.get("meta", {}).get("updated_at"),
            },
            "dpick": dpick_block,
        },
    }


@learning_router.get("/api/mindmap/trail")
async def api_mindmap_trail(limit: int = Query(default=100, ge=1, le=500)):
    """Populated Mindmap trail from Soul-Map, predictions, and scenario memory."""
    try:
        from internal.learning.mindmap_aggregator import collect_trail_events, event_type_counts

        trail = collect_trail_events(limit=limit)
        return {
            "status": "success",
            "trail": trail,
            "count": len(trail),
            "event_type_counts": event_type_counts(trail),
        }
    except Exception as exc:
        logger.warning("mindmap trail failed: %s", exc)
        return {"status": "error", "trail": [], "count": 0, "error": str(exc)}


@learning_router.get("/api/mindmap/state")
async def api_mindmap_state():
    """Aggregator: trail + plain-language panel summaries from live state."""
    try:
        from internal.learning.mindmap_aggregator import build_mindmap_state

        return build_mindmap_state()
    except Exception as exc:
        logger.warning("mindmap state failed: %s", exc)
        return {"status": "error", "trail": [], "summaries": {}, "error": str(exc)}


@learning_router.get("/api/story-strip")
async def api_story_strip(limit: int = Query(default=8, ge=1, le=20)):
    """Compact recent call outcomes for proof-band hydrate."""
    from internal.analytics.story_strip import build_story_strip

    return build_story_strip(limit=limit)


@learning_router.get("/api/mindmap/story-path")
async def api_mindmap_story_path():
    """§21 L5 — linear cause chain for today's council pick."""
    try:
        from internal.council.daily_pick_engine import get_or_create_today_pick
        from internal.learning.story_path import build_story_path

        subnets = _subnets_for_tracker()
        payload = get_or_create_today_pick(subnets, {})
        return {"status": "success", **build_story_path(payload)}
    except Exception as exc:
        logger.warning("mindmap story-path failed: %s", exc)
        return {
            "status": "error",
            "data_available": False,
            "reason": "error",
            "steps": [],
            "error": str(exc),
        }


@learning_router.get("/api/predictions/capsule/{prediction_id}")
async def api_prediction_capsule(prediction_id: str):
    """§21 L12 — time-capsule replay for a graded call."""
    try:
        from internal.learning.prediction_capsule import get_prediction_capsule

        return get_prediction_capsule(prediction_id)
    except Exception as exc:
        logger.warning("prediction capsule failed: %s", exc)
        return {"status": "error", "reason": str(exc)}


@learning_router.get("/api/predictions/capsule/{prediction_id}/og.svg")
async def api_prediction_capsule_og(prediction_id: str):
    """§22 S22-3 — OG share card image for a graded call."""
    from internal.learning.prediction_capsule import build_og_svg, get_prediction_capsule

    data = get_prediction_capsule(prediction_id)
    if data.get("status") != "success":
        svg = build_og_svg(
            {
                "name": "Graded call",
                "correct": None,
                "statement": "Prediction not found or not yet graded.",
            }
        )
    else:
        svg = build_og_svg(data.get("prediction") or {})
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=300"},
    )


@learning_router.get("/api/predictions/capsule/{prediction_id}/og.png")
async def api_prediction_capsule_og_png(prediction_id: str):
    """§23 S23-1 — OG share card PNG for social crawlers."""
    from internal.learning.prediction_capsule import build_og_png, get_prediction_capsule

    data = get_prediction_capsule(prediction_id)
    if data.get("status") != "success":
        png = build_og_png(
            {
                "name": "Graded call",
                "correct": None,
                "statement": "Prediction not found or not yet graded.",
            }
        )
    else:
        png = build_og_png(data.get("prediction") or {})
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


@learning_router.get("/share/call/{prediction_id}", response_class=HTMLResponse)
async def share_call_page(prediction_id: str, request: Request):
    """§22 S22-3 — public share page with OG meta for social crawlers."""
    from internal.learning.prediction_capsule import capsule_share_urls, get_prediction_capsule

    data = get_prediction_capsule(prediction_id)
    if data.get("status") != "success":
        return HTMLResponse(
            """<!DOCTYPE html><html><head><title>Graded call not found</title>
            <meta name="robots" content="noindex"></head>
            <body><p>Prediction not found.</p><p><a href="/">Open SimiVision</a></p></body></html>"""
        )

    pred = data.get("prediction") or {}
    name = pred.get("name") or f"SN{pred.get('netuid', '?')}"
    urls = capsule_share_urls(prediction_id)
    base = os.environ.get("APP_BASE_URL", "").strip().rstrip("/") or str(request.base_url).rstrip("/")
    image_url = f"{base}{urls['share_image_png_url']}"
    page_url = f"{base}{urls['share_page_url']}"
    title = f"SimiVision graded call — {name}"
    desc = (pred.get("statement") or "Direction-graded subnet call from the SimiVision learning loop.")[:200]
    esc = html.escape

    return HTMLResponse(
        f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(desc)}">
  <meta property="og:type" content="article">
  <meta property="og:url" content="{esc(page_url)}">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(desc)}">
  <meta property="og:image" content="{esc(image_url)}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{esc(title)}">
  <meta name="twitter:description" content="{esc(desc)}">
  <meta name="twitter:image" content="{esc(image_url)}">
</head>
<body style="margin:0;background:#0a0a0a;color:#e8f0e9;font-family:system-ui,sans-serif;">
  <main style="max-width:720px;margin:0 auto;padding:24px;text-align:center;">
    <img src="{esc(urls['share_image_png_url'])}" alt="{esc(title)}" style="max-width:100%;height:auto;border-radius:12px;">
    <p style="margin-top:16px;color:#8a9a8e;">{esc(desc)}</p>
    <p><a href="/" style="color:#00ff41;">Open SimiVision Council</a></p>
  </main>
</body>
</html>"""
    )


@learning_router.get("/api/learning/stats")
async def api_learning_stats():
    snap = _learning_snapshot()
    stats = snap["engine_stats"]
    scenario = snap["scenario"]
    resolver_stats = snap["resolver_stats"]
    watchdog = snap["watchdog"]
    trust_banner = snap["trust_banner"]
    return {
        "status": "success",
        "data": {
            "expert_weights": stats.get("expert_weights", {}),
            "total_records": resolver_stats.get("total", stats.get("total_records", 0)),
            "accuracy": resolver_stats.get("accuracy", stats.get("accuracy", 0.0)),
            "correct": resolver_stats.get("correct", 0),
            "wrong": resolver_stats.get("wrong", 0),
            "expired": resolver_stats.get("expired", 0),
            "expired_rate": trust_banner.get("expired_rate"),
            "duplicate": resolver_stats.get("duplicate", 0),
            "pending": resolver_stats.get("pending", stats.get("pending", 0)),
            "graded": trust_banner.get("graded"),
            "last_updated": stats.get("last_updated") or _utcnow_z(),
            "scenario_memory": scenario,
            "watchdog": watchdog,
            "trust_banner": trust_banner,
            "integrity": trust_banner.get("integrity_gate"),
            "brain_ui_ready": trust_banner.get("ready"),
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
        from internal.subnet_names import refresh_stored_names

        data = load_predictions()
        update_stats(data)
        save_predictions(data)
        predictions = refresh_stored_names(data.get("predictions", []))
        resolved = refresh_stored_names(data.get("resolved", []))
        return {
            "predictions": predictions,
            "resolved": resolved,
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
            from internal.subnets.feed import load_pick_subnets

            subnets = load_pick_subnets()
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


def _ensure_resolver_scheduler():
    """Start the resolver scheduler singleton if headless (tests / first trigger)."""
    scheduler = get_prediction_resolver_scheduler()
    if scheduler is None:
        start_prediction_resolver_scheduler(immediate=False)
        scheduler = get_prediction_resolver_scheduler()
    try:
        from internal.council.selector_scheduler import get_selector_scheduler_state, start_selector_scheduler

        if not get_selector_scheduler_state().get("running"):
            start_selector_scheduler(immediate=False)
    except Exception:
        pass
    return scheduler


@learning_router.post("/api/learning/trigger")
async def api_learning_trigger():
    """Manually run a prediction-resolution cycle and return scheduler state."""
    scheduler = _ensure_resolver_scheduler()
    cycle: Dict[str, Any] = {}
    if scheduler is not None:
        try:
            cycle = scheduler.run_once()
        except Exception as exc:
            cycle = {"ok": False, "error": str(exc)}

    return {
        "status": "success",
        "data": {
            "cycle": cycle,
            "scheduler": get_prediction_resolver_scheduler_state(),
            "triggered_at": _utcnow_z(),
        },
    }


@learning_router.post("/api/predictions/resolver/run")
async def api_predictions_resolver_run():
    """Trigger a single prediction-resolution cycle on demand."""
    scheduler = _ensure_resolver_scheduler()
    if scheduler is None:
        return {
            "status": "error",
            "message": "prediction resolver scheduler is not initialized",
        }
    try:
        result = scheduler.run_once()
        return {"status": "success", "data": result}
    except Exception as exc:
        logger.warning("Manual prediction resolver run failed: %s", exc)
        return {"status": "error", "message": str(exc)}


@learning_router.get("/api/scenario-memory")
async def api_scenario_memory():
    """Return the full regime-aware scenario memory snapshot."""
    try:
        from internal.learning.scenario_outcomes import backfill_scenario_outcomes_from_predictions

        backfill_scenario_outcomes_from_predictions()
        return {"status": "ok", **scenario_memory.get_memory_snapshot()}
    except Exception as exc:
        logger.error("Error fetching scenario memory: %s", exc)
        return {
            "status": "error",
            "scenarios": [],
            "regimes": {},
            "stats": {},
            "meta": {},
            "error": str(exc),
        }


@learning_router.post("/api/scenario-memory")
async def api_scenario_memory_add(request: Request):
    """Record a new regime-aware scenario into persistent memory."""
    try:
        payload = await request.json()
    except Exception as exc:
        return {"status": "error", "error": f"Invalid JSON body: {exc}"}

    name = payload.get("name")
    features = payload.get("features", {})
    if not name or not isinstance(features, dict):
        return {"status": "error", "error": "Missing 'name' or 'features'"}

    try:
        scenario = scenario_memory.add_scenario(
            name=name,
            features=features,
            outcome=payload.get("outcome"),
            regime=payload.get("regime"),
            metadata=payload.get("metadata"),
        )
        return {"status": "ok", "scenario": scenario}
    except Exception as exc:
        logger.error("Error adding scenario: %s", exc)
        return {"status": "error", "error": str(exc)}


@learning_router.get("/api/pick-history")
async def api_pick_history():
    """Pick-of-the-Hour history and aggregate success stats."""
    try:
        return pick_history.get_history(limit=20)
    except Exception as exc:
        logger.warning("pick_history.get_history failed: %s", exc)
        return {
            "active": None,
            "history": [],
            "stats": {"total": 0, "wins": 0, "losses": 0, "success_rate": 0.0},
        }


@learning_router.get("/api/rotation-tracker")
async def api_rotation_tracker():
    """Return subnet rotation patterns and volatility clusters."""
    try:
        subnets = _subnets_for_tracker()
        try:
            from internal import freshness_tracker

            freshness_tracker.mark_updated("rotation")
        except Exception:
            pass
        return {"status": "ok", **rotation_tracker.get_rotation_summary(subnets)}
    except Exception as exc:
        logger.error("Error fetching rotation tracker: %s", exc)
        return {"status": "error", "patterns": [], "volatility_clusters": {}, "error": str(exc)}


@learning_router.get("/api/freshness")
async def api_freshness():
    """Per-section last-updated timestamps for dashboard freshness badges."""
    try:
        from internal import freshness_tracker

        return freshness_tracker.snapshot()
    except Exception as exc:
        logger.warning("freshness snapshot failed: %s", exc)
        return {"last_updated": {}, "now": _utcnow_z()}


@learning_router.get("/api/council/weights")
async def api_council_weights():
    """Return the current Council expert weights."""
    try:
        return {"status": "success", "data": load_weights()}
    except Exception as exc:
        logger.warning("load_weights failed: %s", exc)
        return {
            "status": "stub",
            "data": {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0},
            "error": str(exc),
        }


@learning_router.get("/api/formula-lineage")
async def api_formula_lineage_catalog():
    """Cited formula sources, adaptations, and live learning-loop state per lane."""
    try:
        from internal.council.formula_lineage import build_all_lineage

        return build_all_lineage()
    except Exception as exc:
        logger.warning("formula-lineage catalog failed: %s", exc)
        return {"status": "error", "error": str(exc), "lanes": []}


@learning_router.get("/api/formula-lineage/{lane_id}")
async def api_formula_lineage_lane(lane_id: str):
    """Single lane lineage card (council expert or judge)."""
    try:
        from internal.council.formula_lineage import build_lane_lineage

        lane = build_lane_lineage(lane_id.lower().strip())
        if lane is None:
            raise HTTPException(status_code=404, detail="unknown lane")
        return {"status": "ok", "lane": lane}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("formula-lineage lane failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@learning_router.get("/api/formula-lineage/{lane_id}/evolution")
async def api_formula_evolution_trail(lane_id: str):
    """Time-bounded evolution trail: subnets → learning loop → weight/formula state."""
    try:
        from internal.council.formula_evolution import build_evolution_trail

        trail = build_evolution_trail(lane_id.lower().strip())
        if trail is None:
            raise HTTPException(status_code=404, detail="unknown lane")
        return {"status": "ok", **trail}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("formula evolution trail failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@learning_router.get("/api/weights")
async def api_weights():
    """Return learning stats including expert weights."""
    try:
        return LearningEngine().get_stats()
    except Exception as exc:
        logger.warning("api_weights failed: %s", exc)
        return {"status": "error", "error": str(exc)}


@learning_router.get("/api/resolve-predictions")
async def api_resolve_predictions():
    """Trigger prediction resolution for any due predictions."""
    try:
        weights_before = load_weights()
        subnets = _subnets_for_tracker()
        result = resolver.resolve_due_predictions(subnets)
        return {
            "status": "success",
            "data": result,
            "expert_weights_before": weights_before,
            "expert_weights": load_weights(),
        }
    except Exception as exc:
        logger.warning("resolve_due_predictions failed: %s", exc)
        return {
            "status": "stub",
            "data": {"resolved_now": [], "resolved": [], "pending": [], "stats": {}},
            "error": str(exc),
        }


@learning_router.get("/api/rotation-tokens")
async def api_rotation_tokens():
    """Rotation-token watchlist with live CoinGecko prices (60s cache)."""
    try:
        from internal.council.rotation_tokens import build_rotation_tokens_response

        return build_rotation_tokens_response()
    except Exception as exc:
        logger.warning("rotation-tokens failed: %s", exc)
        return {"status": "error", "tokens": [], "error": str(exc)}


try:
    from internal.message_intel.routes import message_intel_router

    learning_router.include_router(message_intel_router)
except ImportError:
    pass

try:
    from internal.pump_tracker.routes import pump_tracker_router

    learning_router.include_router(pump_tracker_router)
except ImportError as _pump_tracker_exc:
    logger.warning("Pump-tracker routes unavailable: %s", _pump_tracker_exc)

try:
    from internal.calibration.routes import calibration_router

    learning_router.include_router(calibration_router)
except ImportError as _calibration_exc:
    logger.warning("Calibration routes unavailable: %s", _calibration_exc)
