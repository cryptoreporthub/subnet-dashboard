"""FastAPI routes for the learning loop (slices 5–11)."""

from __future__ import annotations

import html
import logging
import os
import threading
import time
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from starlette.concurrency import run_in_threadpool

from internal.api_errors import public_error
from internal.rate_limit import limit_or_noop, strict_limit

from datastore.learning_engine import LearningEngine, create_feedback_router
from internal.council import pick_history, resolver, rotation_tracker, scenario_memory
from internal.council.watchdog import check_resolver_watchdog
from internal.council.weights import load_impact_strength, load_weights, load_weights_for_ui
from internal.council.resolver_scheduler import (
    get_prediction_resolver_scheduler,
    get_prediction_resolver_scheduler_state,
    start_prediction_resolver_scheduler,
)
from internal.learning.predictions_store import (
    count_unclassified,
    load_predictions,
    save_predictions,
    update_stats,
)

logger = logging.getLogger(__name__)

learning_router = APIRouter(tags=["learning"])
learning_router.include_router(create_feedback_router())

LEARNING_HEALTH_TIMEOUT = float(os.environ.get("LEARNING_HEALTH_TIMEOUT_SECONDS", "15"))
LEARNING_STATS_TIMEOUT = float(os.environ.get("LEARNING_STATS_TIMEOUT_SECONDS", "10"))
RESOLVER_STATE_TIMEOUT = float(os.environ.get("RESOLVER_STATE_TIMEOUT_SECONDS", "8"))
_LEARNING_HEALTH_CACHE_TTL = float(os.environ.get("LEARNING_HEALTH_CACHE_SECONDS", "10"))
_LEARNING_HEALTH_STALE_TTL = float(os.environ.get("LEARNING_HEALTH_STALE_SECONDS", "60"))
_LEARNING_HEALTH_CACHE: Dict[str, Any] = {"at": 0.0, "payload": None}
_LEARNING_HEALTH_CACHE_LOCK = threading.Lock()
_LEARNING_HEALTH_BUILDING = False
MINDMAP_STATE_HANDLER_TIMEOUT = float(os.environ.get("MINDMAP_STATE_HANDLER_TIMEOUT_SECONDS", "12"))
MINDMAP_SUMMARY_TIMEOUT = float(os.environ.get("MINDMAP_SUMMARY_TIMEOUT_SECONDS", "8"))
_MINDMAP_SUMMARY_TTL = float(os.environ.get("MINDMAP_SUMMARY_CACHE_SECONDS", "60"))
_MINDMAP_SUMMARY_CACHE: Dict[str, Any] = {"at": 0.0, "payload": None}
MINDMAP_STORY_PATH_HANDLER_TIMEOUT = float(
    os.environ.get("MINDMAP_STORY_PATH_HANDLER_TIMEOUT_SECONDS", "12")
)
_STORY_PATH_CACHE: Dict[str, Any] = {"at": 0.0, "payload": None}
_STORY_PATH_CACHE_TTL = float(os.environ.get("MINDMAP_STORY_PATH_CACHE_SECONDS", "30"))


async def _to_thread_timeout(fn, timeout_s: float, *, label: str):
    try:
        from internal.request_executor import REQUEST_EXECUTOR

        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(REQUEST_EXECUTOR, fn),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        logger.warning("%s timed out after %.1fs", label, timeout_s)
        raise


def _learning_health_cacheable(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    if meta.get("source") == "timeout":
        return False
    if payload.get("error") == "timeout":
        return False
    return True


def _learning_health_degraded(
    *,
    source: str,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """Bounded, shape-stable fallback for the public learning-health contract."""
    pick_scheduler: Dict[str, Any] = {}
    daily_pick: Dict[str, Any] = {}
    try:
        from internal.council.pick_scheduler import load_pick_scheduler_state_file
        from internal.learning.loop_health import _daily_pick_today

        file_state = load_pick_scheduler_state_file()
        if isinstance(file_state, dict):
            pick_scheduler = {**file_state, "source": "volume"}
        daily_pick = _daily_pick_today()
    except Exception:
        pass
    return {
        "status": "degraded",
        "meta": {"source": source},
        "checked_at": _utcnow_z(),
        "pending": 0,
        "last_resolver_tick": None,
        "resolver": {
            "running": False,
            "last_ok": None,
            "age_seconds": None,
            "refresh_minutes": None,
            "peer": None,
        },
        "worker_peer": _cheap_worker_peer_hint(),
        "watchdog": {},
        "daily_pick": daily_pick,
        "pick_scheduler": pick_scheduler,
        "ledger": {"required": False, "present": False, "gap": False, "netuid": None},
        "snapshot_age_seconds": None,
        "score_snapshot": {},
        "error": error or source,
    }


def _valid_learning_health(payload: Any) -> bool:
    """Only cache/serve complete health documents so malformed data cannot 422."""
    if not isinstance(payload, dict):
        return False
    required = (
        "status",
        "pending",
        "last_resolver_tick",
        "resolver",
        "worker_peer",
        "watchdog",
        "daily_pick",
        "ledger",
        "snapshot_age_seconds",
        "score_snapshot",
        "checked_at",
    )
    if any(key not in payload for key in required):
        return False
    return all(
        isinstance(payload.get(key), dict)
        for key in ("resolver", "worker_peer", "watchdog", "daily_pick", "ledger", "score_snapshot")
    )


def _get_cached_learning_health(*, allow_stale: bool = False) -> Dict[str, Any] | None:
    now = time.time()
    ttl = _LEARNING_HEALTH_STALE_TTL if allow_stale else _LEARNING_HEALTH_CACHE_TTL
    with _LEARNING_HEALTH_CACHE_LOCK:
        cached = _LEARNING_HEALTH_CACHE.get("payload")
        if isinstance(cached, dict) and now - float(_LEARNING_HEALTH_CACHE.get("at") or 0) < ttl:
            return dict(cached)
    return None


def _learning_health_build_in_flight() -> bool:
    with _LEARNING_HEALTH_CACHE_LOCK:
        return _LEARNING_HEALTH_BUILDING


def _build_learning_health_once() -> Dict[str, Any] | None:
    global _LEARNING_HEALTH_BUILDING
    with _LEARNING_HEALTH_CACHE_LOCK:
        if _LEARNING_HEALTH_BUILDING:
            return None
        _LEARNING_HEALTH_BUILDING = True
    try:
        from internal.learning.loop_health import build_learning_loop_health

        return build_learning_loop_health()
    finally:
        with _LEARNING_HEALTH_CACHE_LOCK:
            _LEARNING_HEALTH_BUILDING = False


def _stale_learning_health(payload: Dict[str, Any]) -> Dict[str, Any]:
    stale = dict(payload)
    meta = dict(stale.get("meta") or {})
    meta.update({"source": "stale_timeout", "stale": True})
    stale["meta"] = meta
    return stale


def _schedule_learning_health_refresh() -> None:
    if _learning_health_build_in_flight():
        return

    def _refresh() -> None:
        try:
            payload = _build_learning_health_once()
            if _valid_learning_health(payload):
                _set_learning_health_cache(payload)
        except Exception as exc:
            logger.debug("learning health background refresh failed: %s", exc)

    threading.Thread(
        target=_refresh,
        daemon=True,
        name="learning-health-refresh",
    ).start()


def _set_learning_health_cache(payload: Dict[str, Any]) -> None:
    if not _learning_health_cacheable(payload) or not _valid_learning_health(payload):
        return
    with _LEARNING_HEALTH_CACHE_LOCK:
        _LEARNING_HEALTH_CACHE["at"] = time.time()
        _LEARNING_HEALTH_CACHE["payload"] = dict(payload)


def _cheap_worker_peer_hint() -> Dict[str, Any]:
    """File/HTTP heartbeat only — safe on learning-health timeout path."""
    try:
        from internal.worker_peer import get_worker_peer

        return get_worker_peer(max_age_seconds=120)
    except Exception as exc:
        logger.debug("cheap worker_peer hint failed: %s", exc)
    try:
        from internal.run_mode import inline_worker_expected
        from internal.worker_heartbeat import is_alive, read_heartbeat

        if inline_worker_expected():
            return {
                "expected": True,
                "alive": is_alive(max_age_seconds=120),
                "heartbeat": read_heartbeat(),
                "peer": "inline_worker",
                "source": "file",
            }
    except Exception:
        pass
    return {}


_LEARNING_DELTA_CORRECT = 0.02
_LEARNING_DELTA_WRONG = -0.03
_LEARNING_SNAPSHOT_TTL = 30.0
_learning_snapshot_lock = threading.Lock()
_learning_snapshot_cache: Dict[str, Any] = {"at": 0.0, "data": None}


def _judge_weights_for_snapshot() -> Dict[str, float]:
    try:
        from internal.judges.weights import DEFAULT_JUDGE_WEIGHTS, normalized_judge_weights

        return normalized_judge_weights()
    except Exception as exc:
        logger.warning("judge weights load failed: %s", exc)
        from internal.judges.weights import DEFAULT_JUDGE_WEIGHTS

        return dict(DEFAULT_JUDGE_WEIGHTS)


def _build_last5_from_resolved(resolved_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Last-5 hit/miss tick arrays for tribunal hero (council + per-judge)."""
    from internal.council.grading import is_pump_desk_claim
    from internal.judges.grading import judge_endorsed, judge_score_at_creation

    resolved = resolved_payload.get("resolved", [])
    gradeable = [
        r
        for r in resolved
        if r.get("outcome") not in {"duplicate", "expired", "ungradeable"}
        and r.get("correct") is not None
        and not is_pump_desk_claim(r)
        and not (r.get("shadow") or r.get("counterfactual"))
    ]
    tail = gradeable[-5:]
    council_last5: List[Any] = [None] * (5 - len(tail)) + [bool(r["correct"]) for r in tail]

    # Per-judge ticks grade each judge's own call (endorse vs abstain vs the
    # outcome) instead of crediting only the leading judge. Judge attribution
    # lives on records that stored judge_scores_at_creation — including
    # shadow/counterfactual replays, whose judge calls and graded outcomes are
    # real even though they stay out of council ticks above.
    attributed = [
        r
        for r in resolved
        if r.get("outcome") not in {"duplicate", "expired", "ungradeable"}
        and r.get("correct") is not None
        and not is_pump_desk_claim(r)
        and isinstance(r.get("judge_scores_at_creation"), dict)
    ]
    judge_last5: Dict[str, List[Any]] = {}
    for judge in ("oracle", "echo", "pulse"):
        ticks: List[bool] = []
        for r in attributed:
            score = judge_score_at_creation(r, judge)
            if score is None:
                continue
            ok = bool(r["correct"])
            ticks.append(ok if judge_endorsed(score, judge) else not ok)
        jtail = ticks[-5:]
        judge_last5[judge] = [None] * (5 - len(jtail)) + jtail

    return {"council_last5": council_last5, "judge_last5": judge_last5}


def _learning_snapshot() -> Dict[str, Any]:
    """Shared ≤30s snapshot for stats / metrics / mindmap (§31-3 O20)."""
    now = time.time()
    with _learning_snapshot_lock:
        if now - float(_learning_snapshot_cache.get("at") or 0) < _LEARNING_SNAPSHOT_TTL:
            cached = _learning_snapshot_cache.get("data")
            if isinstance(cached, dict):
                return cached

        data = load_predictions()
        resolved = data.get("resolved") or []
        pending_rows = data.get("predictions") or []
        resolver_stats = resolver._compute_stats(data)
        weights = load_weights()
        engine_stats = {
            "expert_weights": weights,
            "accuracy": resolver_stats.get("accuracy", 0.0),
            "total_records": resolver_stats.get("total", 0),
            "last_updated": _utcnow_z(),
            "pending": resolver_stats.get("pending", 0),
            "resolved": int(resolver_stats.get("correct", 0) or 0)
            + int(resolver_stats.get("wrong", 0) or 0),
        }
        resolved_payload = {
            "resolved": resolved,
            "predictions": pending_rows,
            "stats": resolver_stats,
        }
        watchdog = check_resolver_watchdog(pending_rows)
        from internal.learning.trust_stats import build_trust_banner

        ledger_context = None
        if os.environ.get("ACCURACY_LIFT_IN_STATS", "0").lower() in ("1", "true", "yes"):
            try:
                from internal.accuracy_lift.measure import build_accuracy_lift_snapshot, iter_resolved

                ledger_rows = iter_resolved(
                    {
                        "resolved": resolved,
                        "predictions": pending_rows,
                    }
                )
                ledger_context = build_accuracy_lift_snapshot(ledger_rows)
            except Exception:
                ledger_context = None

        trust_banner = build_trust_banner(
            resolver_stats,
            watchdog=watchdog,
            ledger_context=ledger_context,
            predictions_data=data,
        )
        from internal.learning.pump_lead_stats import build_pump_desk_trust
        from internal.learning.pump_lead_train import build_pump_evaluation
        from internal.council.grading import is_pump_desk_claim

        pump_desk_trust = build_pump_desk_trust(data)
        pump_evaluation = build_pump_evaluation()
        retryable = sum(
            1
            for row in pending_rows
            if isinstance(row, dict)
            and str(row.get("status") or "pending") == "pending"
            and not is_pump_desk_claim(row)
            and not (row.get("shadow") or row.get("counterfactual"))
        )
        resolver_state = {
            "graded": trust_banner.get("graded", 0),
            "pending": resolver_stats.get("pending", 0),
            "retryable": retryable,
            "expired": resolver_stats.get("expired", 0),
            "gate_reason": trust_banner.get("gate_reason"),
        }
        loop_learned = {
            "status": "ready" if trust_banner.get("ready") else "building",
            "graded": trust_banner.get("graded", 0),
            "pending": resolver_state["pending"],
            "retryable": retryable,
            "gate_reason": trust_banner.get("gate_reason"),
            "weight_updates": 0,
            "evaluation_status": pump_evaluation.get("status"),
        }
        # Weight dials read the mindmap trail (soul map + ledger + dev signals).
        # That scan costs seconds on a warm volume, so it belongs in this cached
        # snapshot — the request handlers must never run it on the event loop.
        from internal.learning.weight_deltas import (
            collect_weight_trail_events,
            expert_graded_counts,
            recent_expert_weight_deltas,
            recent_judge_weight_deltas,
        )

        trail_events = collect_weight_trail_events()
        alignment_diagnostic_events = sum(
            1
            for event in trail_events
            if isinstance(event, dict)
            and (
                str(event.get("decision") or "").startswith("alignment_")
                or (isinstance(event.get("evidence"), dict)
                    and event["evidence"].get("outcome_weight_changed") is False)
            )
        )
        snapshot = {
            "engine_stats": engine_stats,
            "expert_weight_deltas": recent_expert_weight_deltas(events=trail_events),
            "judge_weight_deltas": recent_judge_weight_deltas(events=trail_events),
            "expert_graded_counts": expert_graded_counts(),
            "resolver_stats": resolver_stats,
            "resolved_payload": resolved_payload,
            "pending_rows": pending_rows,
            "predictions_data": data,
            "watchdog": watchdog,
            "trust_banner": trust_banner,
            "pump_desk_trust": pump_desk_trust,
            "pump_evaluation": pump_evaluation,
            "resolver_state": resolver_state,
            "loop_learned": loop_learned,
            "recent": resolved[-10:],
            "scenario": _scenario_memory_summary(),
            "expert_weights": weights,
            "judge_weights": _judge_weights_for_snapshot(),
            "judge_last5": _build_last5_from_resolved(resolved_payload)["judge_last5"],
            "council_last5": _build_last5_from_resolved(resolved_payload)["council_last5"],
            "alignment_diagnostic_events": alignment_diagnostic_events,
        }
        _learning_snapshot_cache["at"] = now
        _learning_snapshot_cache["data"] = snapshot
        return snapshot


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _learning_stats_payload(
    snap: Dict[str, Any],
    *,
    status: str = "success",
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not isinstance(snap, dict):
        raise ValueError("learning snapshot is not an object")
    stats = snap.get("engine_stats") or {}
    resolver_stats = snap.get("resolver_stats") or {}
    watchdog = snap.get("watchdog") or {}
    trust_banner = snap["trust_banner"]
    predictions_data = snap.get("predictions_data")
    unclassified = count_unclassified(predictions_data)
    payload = {
        "status": status,
        "data": {
            "expert_weights": stats.get("expert_weights", {}),
            "judge_weights": snap.get("judge_weights", {}),
            "judge_weight_deltas": snap.get("judge_weight_deltas", {}),
            "expert_weight_deltas": snap.get("expert_weight_deltas", {}),
            "expert_graded_counts": snap.get("expert_graded_counts", {}),
            "judge_last5": snap.get("judge_last5", {}),
            "council_last5": snap.get("council_last5", []),
            "total_records": resolver_stats.get("total", stats.get("total_records", 0)),
            "accuracy": resolver_stats.get("accuracy", stats.get("accuracy", 0.0)),
            "correct": resolver_stats.get("correct", 0),
            "wrong": resolver_stats.get("wrong", 0),
            "expired": resolver_stats.get("expired", 0),
            "expired_genuine": resolver_stats.get("expired_genuine", 0),
            "ungradeable": resolver_stats.get("ungradeable", 0),
            "price_data_unavailable": resolver_stats.get("price_data_unavailable", 0),
            "expired_rate": trust_banner.get("expired_rate"),
            "duplicate": resolver_stats.get("duplicate", 0),
            "pending": resolver_stats.get("pending", stats.get("pending", 0)),
            "council_pending": resolver_stats.get(
                "council_pending", resolver_stats.get("pending", stats.get("pending", 0))
            ),
            "pump_pending": resolver_stats.get("pump_pending", 0),
            "total_pending": resolver_stats.get(
                "total_pending", resolver_stats.get("pending", stats.get("pending", 0))
            ),
            "graded": trust_banner.get("graded"),
            "unclassified_count": unclassified,
            "last_updated": stats.get("last_updated") or _utcnow_z(),
            "scenario_memory": snap.get("scenario"),
            "watchdog": watchdog,
            "trust_banner": trust_banner,
            "pump_desk_trust": snap.get("pump_desk_trust"),
            "pump_evaluation": snap.get("pump_evaluation"),
            "resolver_state": snap.get("resolver_state"),
            "loop_learned": snap.get("loop_learned"),
            "integrity": trust_banner.get("integrity_gate"),
            "brain_ui_ready": trust_banner.get("ready"),
            "alignment_diagnostic_events": snap.get("alignment_diagnostic_events", 0),
        },
    }
    if meta:
        payload["meta"] = meta
    return payload


def _learning_stats_degraded(*, source: str = "timeout") -> Dict[str, Any]:
    from internal.learning.trust_stats import build_trust_banner

    stale = _learning_snapshot_cache.get("data")
    if isinstance(stale, dict):
        return _learning_stats_payload(stale, status="degraded", meta={"source": source})
    trust_banner = build_trust_banner(
        {"correct": 0, "wrong": 0, "expired": 0, "duplicate": 0, "pending": 0, "total": 0}
    )
    trust_banner["ready"] = False
    trust_banner["message"] = "Learning stats warming up"
    return {
        "status": "degraded",
        "meta": {"source": source},
        "data": {
            "expert_weights": {},
            "judge_weights": {},
            "judge_weight_deltas": {},
            "judge_last5": {},
            "council_last5": [],
            "total_records": 0,
            "accuracy": None,
            "correct": 0,
            "wrong": 0,
            "expired": 0,
            "expired_genuine": 0,
            "ungradeable": 0,
            "price_data_unavailable": 0,
            "expired_rate": None,
            "duplicate": 0,
            "pending": 0,
            "council_pending": 0,
            "pump_pending": 0,
            "total_pending": 0,
            "graded": 0,
            "unclassified_count": 0,
            "last_updated": _utcnow_z(),
            "scenario_memory": {},
            "watchdog": {},
            "trust_banner": trust_banner,
            "pump_desk_trust": {
                "ready": False,
                "line": "Pump early hit-rate warming up",
                "early": {"n": 0, "hits": 0, "hit_rate": None},
                "min_sample_trust": 5,
            },
            "pump_evaluation": {
                "status": "insufficient_sample",
                "rows": 0,
                "holdout": {"n": 0},
                "adaptation_gate": {
                    "sample_ok": False,
                    "beats_baseline": False,
                    "passed": False,
                },
            },
            "resolver_state": {
                "graded": 0,
                "pending": 0,
                "retryable": 0,
                "expired": 0,
                "gate_reason": "learning_stats_timeout",
            },
            "loop_learned": {
                "status": "warming_up",
                "graded": 0,
                "pending": 0,
                "retryable": 0,
                "gate_reason": "learning_stats_timeout",
            },
            "integrity": trust_banner.get("integrity_gate"),
            "brain_ui_ready": False,
            "alignment_diagnostic_events": 0,
        },
    }


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


def _compute_learning_metrics(snap: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if snap is None:
        snap = _learning_snapshot()
    stats = snap["engine_stats"]
    resolver_stats = snap["resolver_stats"]
    watchdog = snap["watchdog"]
    trust_banner = snap["trust_banner"]
    recent = snap["recent"]
    return {
        "expert_weights": stats.get("expert_weights", {}),
        "judge_weights": snap.get("judge_weights", {}),
        "judge_last5": snap.get("judge_last5", {}),
        "council_last5": snap.get("council_last5", []),
        "expert_weight_deltas": snap.get("expert_weight_deltas", {}),
        "expert_graded_counts": snap.get("expert_graded_counts", {}),
        "judge_weight_deltas": snap.get("judge_weight_deltas", {}),
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
        "pump_desk_trust": snap.get("pump_desk_trust"),
        "pump_evaluation": snap.get("pump_evaluation"),
        "resolver_state": snap.get("resolver_state"),
        "loop_learned": snap.get("loop_learned"),
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


def _mindmap_conviction_block(daily_payload: Dict[str, Any] | None) -> Dict[str, Any]:
    """RF-2: no fake 50% — daily pick conviction when present, else honest-empty."""
    conf = None
    if isinstance(daily_payload, dict):
        for key in ("final_confidence", "confidence"):
            raw = daily_payload.get(key)
            if raw is not None:
                conf = raw
                break
        if conf is None:
            pick = daily_payload.get("pick") if isinstance(daily_payload.get("pick"), dict) else {}
            cand = daily_payload.get("candidate") if isinstance(daily_payload.get("candidate"), dict) else {}
            conf = pick.get("final_confidence") or pick.get("confidence") or cand.get("final_confidence")
    if conf is not None:
        try:
            val = float(conf)
            pct = round(val * 100, 1) if val <= 1.0 else round(val, 1)
            return {
                "data_available": True,
                "current": pct,
                "trend": "stable",
                "explanation": "From today's daily call conviction",
            }
        except (TypeError, ValueError):
            pass
    return {
        "data_available": False,
        "current": None,
        "trend": None,
        "explanation": "No aggregated conviction — see daily call and Living Focus",
    }


def _mindmap_summary_degraded(*, source: str = "timeout") -> Dict[str, Any]:
    try:
        expert_weights = load_weights_for_ui()
    except Exception:
        expert_weights = {}
    return {
        "status": "degraded",
        "meta": {"source": source},
        "data": {
            "conviction": _mindmap_conviction_block(None),
            "expert_insights": [
                {"expert": name.title(), "weight": weight}
                for name, weight in expert_weights.items()
            ],
            "expert_weights": expert_weights,
            "resolved_predictions": {},
            "scenario_memory": {},
            "rotation_tracker": {},
            "learning_status": {"enabled": True, "records": 0, "last_updated": None},
            "dpick": {"shortlist": []},
            "engine_stats": {},
            "simivision_meta": {},
        },
    }


@learning_router.get("/api/mindmap/summary")
async def api_mindmap_summary():
    """Mindmap summary — file-backed pick + soul_map weights only (no resolver/scoring)."""
    return _build_mindmap_summary_cached()


def _kick_mindmap_summary_refresh() -> None:
    # ponytail: no-op — bg refresh held GIL (LearningEngine/resolver) and starved the event loop.
    return


def _build_mindmap_summary_cached() -> Dict[str, Any]:
    now = time.time()
    cached = _MINDMAP_SUMMARY_CACHE.get("payload")
    if isinstance(cached, dict) and now - float(_MINDMAP_SUMMARY_CACHE.get("at") or 0) < _MINDMAP_SUMMARY_TTL:
        return cached
    payload = _build_mindmap_summary()
    _MINDMAP_SUMMARY_CACHE["payload"] = payload
    _MINDMAP_SUMMARY_CACHE["at"] = time.time()
    return payload


def _build_mindmap_summary() -> Dict[str, Any]:
    daily_payload = _load_today_pick_payload_lite()
    shortlist = daily_payload.get("shortlist")
    dpick_block = {"shortlist": shortlist if isinstance(shortlist, list) else []}
    conviction_block = _mindmap_conviction_block(daily_payload)

    try:
        expert_weights = load_weights_for_ui()
    except Exception as exc:
        logger.warning("Could not load expert weights for mindmap summary: %s", exc)
        expert_weights = {}

    return {
        "status": "success",
        "data": {
            "conviction": conviction_block,
            "expert_insights": [
                {"expert": name.title(), "weight": weight}
                for name, weight in expert_weights.items()
            ],
            "expert_weights": expert_weights,
            "resolved_predictions": {},
            "scenario_memory": {},
            "rotation_tracker": {},
            "learning_status": {"enabled": True, "records": 0, "last_updated": None},
            "dpick": dpick_block,
            "engine_stats": {},
            "simivision_meta": {},
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
    from internal.learning.mindmap_aggregator import build_mindmap_state

    try:
        return await _to_thread_timeout(
            build_mindmap_state, MINDMAP_STATE_HANDLER_TIMEOUT, label="mindmap-state"
        )
    except asyncio.TimeoutError:
        from internal.learning.mindmap_aggregator import get_stale_mindmap_state

        stale = get_stale_mindmap_state()
        if stale:
            out = dict(stale)
            out["status"] = "cached"
            return out
        try:
            from internal.learning.mindmap_aggregator import _build_integration_status

            integration_status = _build_integration_status()
        except Exception:
            integration_status = {}
        return {
            "status": "timeout",
            "trail": [],
            "trail_count": 0,
            "event_type_counts": {},
            "summaries": {},
            "schedulers": {},
            "integration_status": integration_status,
        }
    except Exception as exc:
        logger.warning("mindmap state failed: %s", exc)
        return {"status": "error", "trail": [], "summaries": {}, "error": str(exc)}


@learning_router.get("/api/story-strip")
async def api_story_strip(
    limit: int = Query(default=8, ge=1, le=20),
    focus: int | None = Query(default=None, ge=1),
):
    """Compact recent call outcomes for proof-band hydrate."""
    from internal.analytics.story_strip import build_story_strip

    return build_story_strip(limit=limit, focus_netuid=focus)


@learning_router.get("/api/mindmap/story-path")
async def api_mindmap_story_path():
    """§21 L5 — linear cause chain for today's council pick."""
    try:
        return await _to_thread_timeout(
            _build_mindmap_story_path,
            MINDMAP_STORY_PATH_HANDLER_TIMEOUT,
            label="mindmap-story-path",
        )
    except asyncio.TimeoutError:
        stale = _get_stale_story_path()
        if stale:
            out = dict(stale)
            out["status"] = "cached"
            return out
        return {
            "status": "timeout",
            "data_available": False,
            "reason": "timeout",
            "steps": [],
        }
    except Exception as exc:
        logger.warning("mindmap story-path failed: %s", exc)
        return {
            "status": "error",
            "data_available": False,
            "reason": "error",
            "steps": [],
            "error": str(exc),
        }


def _load_today_pick_payload_lite() -> Dict[str, Any]:
    """File-backed daily pick — no live subnet-universe scoring."""
    from internal.council.daily_pick_engine import _find_today, _load

    daily = _find_today(_load())
    return daily if isinstance(daily, dict) else {}


def _get_stale_story_path() -> Dict[str, Any] | None:
    cached = _STORY_PATH_CACHE.get("payload")
    if isinstance(cached, dict):
        return dict(cached)
    return None


def _build_mindmap_story_path() -> Dict[str, Any]:
    now = time.monotonic()
    cached = _STORY_PATH_CACHE.get("payload")
    if isinstance(cached, dict) and now - float(_STORY_PATH_CACHE.get("at") or 0) < _STORY_PATH_CACHE_TTL:
        return dict(cached)

    from internal.learning.story_path import build_story_path

    payload = _load_today_pick_payload_lite()
    out = {"status": "success", **build_story_path(payload)}
    _STORY_PATH_CACHE["at"] = now
    _STORY_PATH_CACHE["payload"] = out
    return out


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


@learning_router.get("/api/learning/health")
async def api_learning_loop_health():
    """Phase 0 — pick→ledger→resolver loop status (no scoring)."""
    cached = _get_cached_learning_health()
    if cached is not None:
        return cached
    if _learning_health_build_in_flight():
        stale = _get_cached_learning_health(allow_stale=True)
        return _stale_learning_health(stale) if stale is not None else _learning_health_degraded(source="refreshing")

    try:
        payload = await _to_thread_timeout(
            _build_learning_health_once, LEARNING_HEALTH_TIMEOUT, label="learning-health"
        )
        if payload is None:
            stale = _get_cached_learning_health(allow_stale=True)
            return _stale_learning_health(stale) if stale is not None else _learning_health_degraded(source="refreshing")
        if _valid_learning_health(payload):
            _set_learning_health_cache(payload)
            return payload
        logger.warning("learning health returned malformed payload")
        return _learning_health_degraded(source="invalid_payload", error="invalid_payload")
    except asyncio.TimeoutError:
        stale = _get_cached_learning_health(allow_stale=True)
        if stale is not None:
            return _stale_learning_health(stale)
        _schedule_learning_health_refresh()
        return _learning_health_degraded(source="timeout")
    except Exception as exc:
        logger.warning("learning health failed: %s", exc)
        return _learning_health_degraded(source="error", error="health_probe_failed")


@learning_router.get("/api/learning/stats")
async def api_learning_stats():
    try:
        snap = await _to_thread_timeout(
            _learning_snapshot, LEARNING_STATS_TIMEOUT, label="learning-stats"
        )
        return _learning_stats_payload(snap)
    except asyncio.TimeoutError:
        return _learning_stats_degraded(source="timeout")
    except Exception as exc:
        logger.warning("learning stats failed: %s", exc)
        return _learning_stats_degraded(source="error")


@learning_router.post("/api/learning/rebalance-weights")
@limit_or_noop(strict_limit(), override_defaults=True)
async def api_learning_rebalance_weights(
    request: Request,
    replay_share: float = Query(default=0.7, ge=0.0, le=1.0),
    dry_run: bool = Query(default=False),
):
    """Slice R — replay council weights from ledger with re-attribution + soft reset."""
    from internal.council.weights import rebalance_council_weights

    try:
        result = rebalance_council_weights(replay_share=replay_share, save=not dry_run)
        _learning_snapshot_cache["at"] = 0.0
        return {"status": "success", "data": result}
    except Exception as exc:
        logger.error("rebalance-weights failed: %s", exc)
        raise HTTPException(status_code=500, detail=public_error(exc, code="rebalance_failed")["error"]) from exc


@learning_router.post("/api/learning/backfill-expert-attribution")
@limit_or_noop(strict_limit(), override_defaults=True)
async def api_backfill_expert_attribution(
    request: Request,
    dry_run: bool = Query(default=True),
):
    """Re-stamp council expert labels on ledger rows (dry_run default true; expert fields only)."""
    from internal.learning.expert_backfill import backfill_expert_attribution

    try:
        result = await run_in_threadpool(backfill_expert_attribution, dry_run=bool(dry_run))
        if not dry_run:
            _learning_snapshot_cache["at"] = 0.0
        return {"status": "success", "data": result}
    except Exception as exc:
        logger.error("backfill-expert-attribution failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=public_error(exc, code="expert_backfill_failed")["error"],
        ) from exc


@learning_router.get("/api/learning-metrics")
async def api_learning_metrics():
    try:
        snap = await _to_thread_timeout(
            _learning_snapshot, LEARNING_STATS_TIMEOUT, label="learning-metrics"
        )
        return _compute_learning_metrics(snap)
    except asyncio.TimeoutError:
        degraded = _learning_stats_degraded(source="timeout")
        return {
            "error": "timeout",
            "expert_weights": degraded["data"].get("expert_weights", {}),
            "accuracy": degraded["data"].get("accuracy", 0.0),
            "trust_banner": degraded["data"].get("trust_banner"),
        }


@learning_router.get("/api/predictions")
async def api_predictions():
    try:
        from internal.subnet_names import refresh_stored_names

        data = load_predictions()
        predictions = refresh_stored_names(data.get("predictions", []))
        resolved = refresh_stored_names(data.get("resolved", []))
        stats = resolver._compute_stats(data)
        return {
            "predictions": predictions,
            "resolved": resolved,
            "stats": stats,
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


def _resolver_state_cross_process() -> Dict[str, Any]:
    """Resolver truth for the web process — the scheduler lives on the worker.

    In prod the web process serves HTTP only (``BACKGROUND_ON_WEB=off``), so its
    in-memory scheduler singleton is never started and reports ``running=false``
    / ``last_run_at=null`` even while the inline worker is ticking normally.
    The shared volume holds the real evidence: the resolver's cycle summary in
    the soul map plus the worker heartbeat.
    """
    from internal.run_mode import worker_mode_label

    state = dict(get_prediction_resolver_scheduler_state())
    state["in_process"] = {
        "running": state.get("running"),
        "last_run_at": state.get("last_run_at"),
    }
    try:
        from internal.learning.loop_health import _last_resolver_tick
    except Exception:
        state["source"] = "memory"
        return state

    try:
        tick = _last_resolver_tick()
    except Exception as exc:
        logger.warning("resolver cross-process state failed: %s", exc)
        state["source"] = "memory"
        return state

    peer = tick.get("worker_peer") if isinstance(tick.get("worker_peer"), dict) else {}
    state["running"] = bool(tick.get("running"))
    if tick.get("at"):
        state["last_run_at"] = tick.get("at")
        state["last_run_ok"] = tick.get("ok")
    state["refresh_minutes"] = tick.get("refresh_minutes") or state.get("refresh_minutes")
    state["worker_peer"] = peer
    state["run_mode"] = worker_mode_label()
    state["source"] = "volume" if tick.get("at") else "memory"
    return state


@learning_router.get("/api/predictions/resolver")
async def api_predictions_resolver_state():
    try:
        data = await _to_thread_timeout(
            _resolver_state_cross_process,
            RESOLVER_STATE_TIMEOUT,
            label="resolver-state",
        )
    except asyncio.TimeoutError:
        data = {**get_prediction_resolver_scheduler_state(), "source": "memory", "error": "timeout"}
    except Exception as exc:
        logger.warning("resolver state failed: %s", exc)
        data = {
            **get_prediction_resolver_scheduler_state(),
            "source": "memory",
            "error": "state_unavailable",
        }
    return {"status": "success", "data": data}


def _resolver_allowed_on_this_process() -> bool:
    """Prod web serves HTTP only — resolver runs on inline worker."""
    from internal.run_mode import background_on_web, is_worker_mode

    return is_worker_mode() or background_on_web()


def _ensure_resolver_scheduler():
    """Start the resolver scheduler singleton if headless (tests / first trigger)."""
    if not _resolver_allowed_on_this_process():
        return None
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
@limit_or_noop(strict_limit(), override_defaults=True)
async def api_learning_trigger(request: Request):
    """Manually run a prediction-resolution cycle and return scheduler state."""
    if not _resolver_allowed_on_this_process():
        raise HTTPException(
            status_code=503,
            detail="prediction resolver runs on background worker only (BACKGROUND_ON_WEB=off)",
        )
    scheduler = _ensure_resolver_scheduler()
    cycle: Dict[str, Any] = {}
    if scheduler is not None:
        try:
            cycle = scheduler.run_once()
        except Exception as exc:
            cycle = {"ok": False, **public_error(exc, code="resolver_cycle_failed")}

    return {
        "status": "success",
        "data": {
            "cycle": cycle,
            "scheduler": get_prediction_resolver_scheduler_state(),
            "triggered_at": _utcnow_z(),
        },
    }


@learning_router.post("/api/predictions/resolver/run")
@limit_or_noop(strict_limit(), override_defaults=True)
async def api_predictions_resolver_run(request: Request):
    """Trigger a single prediction-resolution cycle on demand."""
    if not _resolver_allowed_on_this_process():
        raise HTTPException(
            status_code=503,
            detail="prediction resolver runs on background worker only (BACKGROUND_ON_WEB=off)",
        )
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
        return {"status": "error", **public_error(exc, code="resolver_run_failed")}


@learning_router.post("/api/learning/pump-lead/recover")
@limit_or_noop(strict_limit(), override_defaults=True)
async def api_pump_lead_recover(request: Request, dry_run: bool = False, hydrate: bool = True):
    """Candle-grade overdue pump_lead backlog (quality filter; no late live prices).

    hydrate=true (default): fetch OHLCV for overdue quality netuids before grading
    so cold price_cache does not burn samples as missing_horizon_candles.
    """
    try:
        from internal.learning.pump_lead_recover import recover_overdue_pump_leads

        summary = recover_overdue_pump_leads(
            dry_run=bool(dry_run), hydrate=bool(hydrate)
        )
        return {"status": "success", "data": summary}
    except Exception as exc:
        logger.warning("pump_lead recover failed: %s", exc)
        return {"status": "error", **public_error(exc, code="pump_lead_recover_failed")}


@learning_router.get("/api/learning/pump-lead/train-status")
async def api_pump_lead_train_status():
    """Upgrade-6 dataset gate: gradeable n, frozen features, ready_to_train."""
    try:
        from internal.learning.pump_lead_train import build_pump_evaluation, dataset_status

        return {
            "status": "success",
            "data": {
                **dataset_status(),
                "evaluation": build_pump_evaluation(),
            },
        }
    except Exception as exc:
        logger.warning("pump_lead train-status failed: %s", exc)
        return {"status": "error", "message": str(exc)}


@learning_router.post("/api/learning/pump-lead/train")
@limit_or_noop(strict_limit(), override_defaults=True)
async def api_pump_lead_train(request: Request, dry_run: bool = True):
    """Export train matrix; fit XGBoost stub only when n>=50 and package present.

    Never swaps prod hand score (ready_for_prod_replace still n>=100 + explicit).
    """
    try:
        from internal.learning.pump_lead_train import train_offline

        summary = train_offline(dry_run=bool(dry_run))
        return {"status": "success", "data": summary}
    except Exception as exc:
        logger.warning("pump_lead train failed: %s", exc)
        return {"status": "error", **public_error(exc, code="pump_lead_train_failed")}


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
@limit_or_noop(strict_limit(), override_defaults=True)
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
        return {"status": "success", "data": load_weights_for_ui()}
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
