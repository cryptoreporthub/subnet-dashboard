"""Mindmap trail aggregator — merges live Soul-Map, predictions, and scenario diffs."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

from internal.learning.trail_bus import CANONICAL_EVENT_TYPES, normalize_event_type

logger = logging.getLogger(__name__)

_STATE_CACHE: Dict[str, Any] = {"at": 0.0, "payload": None}
_STATE_CACHE_TTL = float(os.environ.get("MINDMAP_STATE_CACHE_SECONDS", "30"))

_INTEGRATION_STATUS_VALUES = frozenset(
    {"closed", "partial", "blocked", "display_only", "read_only"}
)


def _judges_integration_status() -> str:
    """closed when #720's per-judge weights module is importable and wired into scoring."""
    try:
        from internal.judges.weights import normalized_judge_weights
        from internal.judges import subnet_judges  # noqa: F401 — proves scoring module present

        # Touch the public API so a stub module without the function fails closed→blocked
        normalized_judge_weights  # reference only; don't call (avoids soul_map IO on every graph build)
        return "closed"
    except Exception:
        return "blocked"


def _dispositions_integration_status() -> str:
    """partial when §30-6 disposition_score_adjustment is importable (wired in state_vector scoring)."""
    try:
        from internal.council.memory_scoring import disposition_score_adjustment

        disposition_score_adjustment  # reference only; don't call (avoids soul_map IO)
        return "partial"
    except Exception:
        return "display_only"


def _scenario_integration_status() -> str:
    """partial when §30-7 scenario_outcome_adjustment is importable (wired in state_vector scoring)."""
    try:
        from internal.council.memory_scoring import scenario_outcome_adjustment

        scenario_outcome_adjustment  # reference only; don't call (avoids soul_map IO)
        return "partial"
    except Exception:
        return "display_only"


def _build_integration_status() -> Dict[str, str]:
    return {
        "council_trail": "closed",
        "expert_weights": "closed",
        "judges": _judges_integration_status(),
        "telegram_pulse": "partial",
        "dispositions": _dispositions_integration_status(),
        "scenario": _scenario_integration_status(),
        "pump_desk": "partial",
        "whales_indicators": "read_only",
    }


def _parse_time(entry: Dict[str, Any]) -> str:
    return str(entry.get("time") or entry.get("created_at") or "")


def _trail_from_soul_map() -> List[Dict[str, Any]]:
    try:
        from internal.council.weights import _load_raw

        data = _load_raw()
        trail = (data.get("soul_map_state") or {}).get("learning_trail") or []
        if isinstance(trail, list):
            return [dict(row) for row in trail if isinstance(row, dict)]
    except Exception as exc:
        logger.warning("soul_map trail read failed: %s", exc)
    return []


def _trail_from_predictions() -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    try:
        from internal.learning.predictions_store import load_predictions

        data = load_predictions()
        for pred in (data.get("predictions") or [])[:20]:
            if not isinstance(pred, dict):
                continue
            events.append(
                {
                    "time": pred.get("created_at"),
                    "event_type": "signal_triggered",
                    "subnet": pred.get("name"),
                    "netuid": pred.get("netuid"),
                    "signal": pred.get("signal_source") or "pending_prediction",
                    "decision": pred.get("direction"),
                    "prediction": pred.get("statement"),
                    "judge": pred.get("expert"),
                    "evidence": {
                        "prediction_id": pred.get("id"),
                        "horizon_type": pred.get("horizon_type"),
                        "status": "pending",
                    },
                }
            )
        for pred in (data.get("resolved") or [])[-30:]:
            if not isinstance(pred, dict):
                continue
            events.append(
                {
                    "time": pred.get("resolved_at") or pred.get("created_at"),
                    "event_type": "prediction_resolved",
                    "subnet": pred.get("name"),
                    "netuid": pred.get("netuid"),
                    "signal": pred.get("signal_source"),
                    "decision": "hit" if pred.get("correct") else pred.get("outcome"),
                    "prediction": pred.get("statement"),
                    "judge": pred.get("expert"),
                    "evidence": {
                        "prediction_id": pred.get("id"),
                        "actual_pct": pred.get("actual_pct"),
                        "correct": pred.get("correct"),
                        "return_driver": (pred.get("subnet_snapshot") or {}).get("return_driver"),
                        "yield_trap": (pred.get("subnet_snapshot") or {}).get("yield_trap"),
                        "price_change_7d": (pred.get("subnet_snapshot") or {}).get("price_change_7d"),
                        "active_signals": pred.get("active_signals"),
                    },
                }
            )
    except Exception as exc:
        logger.warning("predictions trail derive failed: %s", exc)
    return events


def _trail_from_dev_signals() -> List[Dict[str, Any]]:
    """Notable dev-ahead-of-price spikes from dev_radar_cache (display-only)."""
    events: List[Dict[str, Any]] = []
    try:
        from internal.dev_radar.github_sync import load_dev_radar_cache

        cache = load_dev_radar_cache()
        subnets = cache.get("subnets") if isinstance(cache.get("subnets"), dict) else {}
        for key, row in subnets.items():
            if not isinstance(row, dict) or row.get("gap_signal") != "dev_ahead_of_price":
                continue
            try:
                netuid = int(key)
            except (TypeError, ValueError):
                continue
            events.append(
                {
                    "time": row.get("synced_at") or cache.get("updated_at"),
                    "event_type": "signal_triggered",
                    "netuid": netuid,
                    "signal": "dev_radar",
                    "decision": "dev_ahead_of_price",
                    "evidence": {
                        "gap_score": row.get("gap_score"),
                        "velocity_score": row.get("velocity_score"),
                        "commits_7d": row.get("commits_7d"),
                    },
                }
            )
        events.sort(
            key=lambda r: float((r.get("evidence") or {}).get("gap_score") or 0),
            reverse=True,
        )
    except Exception as exc:
        logger.warning("dev signals trail derive failed: %s", exc)
    return events[:10]


def _trail_from_scenario_memory() -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    try:
        from internal.council import scenario_memory

        snap = scenario_memory.get_memory_snapshot()
        for scen in (snap.get("scenarios") or [])[-15:]:
            if not isinstance(scen, dict):
                continue
            events.append(
                {
                    "time": scen.get("created_at") or scen.get("updated_at"),
                    "event_type": "scenario_tagged",
                    "subnet": scen.get("name"),
                    "signal": "scenario_memory",
                    "decision": scen.get("outcome") or "pending",
                    "evidence": {
                        "scenario_id": scen.get("id"),
                        "regime": scen.get("regime"),
                        "features": scen.get("features"),
                    },
                }
            )
    except Exception as exc:
        logger.warning("scenario trail derive failed: %s", exc)
    return events


def _trail_from_weight_snapshot() -> List[Dict[str, Any]]:
    """Live accuracy baseline when no historical trail rows exist yet."""
    try:
        from internal.council import resolver
        from internal.council.weights import load_weights
        from internal.learning.trail_events import _now_z

        stats = resolver.get_resolved_predictions().get("stats") or {}
        weights = load_weights()
        return [
            {
                "time": _now_z(),
                "event_type": "accuracy_update",
                "signal": "mindmap_aggregator",
                "decision": "live_snapshot",
                "evidence": {
                    "accuracy": stats.get("accuracy", 0),
                    "correct": stats.get("correct", 0),
                    "wrong": stats.get("wrong", 0),
                    "pending": stats.get("pending", 0),
                    "expert_weights": weights,
                },
            }
        ]
    except Exception:
        return []


def _dedupe_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for row in events:
        pid = (row.get("evidence") or {}).get("prediction_id")
        key = (
            row.get("event_type"),
            pid,
            row.get("time"),
            row.get("netuid"),
            row.get("signal"),
        )
        if key in seen:
            continue
        seen.add(key)
        normalized = dict(row)
        normalized["event_type"] = normalize_event_type(row.get("event_type"))
        out.append(normalized)
    out.sort(key=_parse_time, reverse=True)
    return out


def _refresh_trail_names(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Re-resolve display names from netuid at read time (plan §1.6)."""
    from internal.subnet_names import name_for_netuid

    out: List[Dict[str, Any]] = []
    for row in events or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        netuid = item.get("netuid")
        if netuid is None:
            evidence = item.get("evidence")
            if isinstance(evidence, dict):
                netuid = evidence.get("netuid")
        if netuid is not None:
            try:
                item["subnet"] = name_for_netuid(int(netuid), use_taostats=False)
            except (TypeError, ValueError):
                pass
        out.append(item)
    return out


def collect_trail_events(limit: int = 100) -> List[Dict[str, Any]]:
    """Merge persisted trail rows with derived prediction/scenario events."""
    merged: List[Dict[str, Any]] = []
    merged.extend(_trail_from_soul_map())
    merged.extend(_trail_from_predictions())
    merged.extend(_trail_from_dev_signals())
    merged.extend(_trail_from_scenario_memory())
    merged = _dedupe_events(merged)
    if not merged:
        merged = _trail_from_weight_snapshot()
    return _refresh_trail_names(merged[:limit])


def event_type_counts(events: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {t: 0 for t in CANONICAL_EVENT_TYPES}
    for row in events:
        et = normalize_event_type(row.get("event_type"))
        if et in counts:
            counts[et] += 1
        else:
            counts["signal_triggered"] += 1
    return counts


def build_mindmap_state() -> Dict[str, Any]:
    now = time.monotonic()
    cached = _STATE_CACHE.get("payload")
    if isinstance(cached, dict) and now - float(_STATE_CACHE.get("at") or 0) < _STATE_CACHE_TTL:
        return dict(cached)

    from internal.learning import panel_summaries

    trail = collect_trail_events()
    summaries: Dict[str, Any] = {
        "council": panel_summaries.summarize_council(),
        "judges": panel_summaries.summarize_judges(),
        "learning": panel_summaries.summarize_learning(),
        "picks": panel_summaries.summarize_picks_lite(),
    }
    pump = panel_summaries.summarize_pump_guarded()
    if pump:
        summaries["pump"] = pump
    scenario = panel_summaries.summarize_scenario_guarded()
    if scenario:
        summaries["scenario"] = scenario
    message_intel = panel_summaries.summarize_message_intel_guarded()
    if message_intel:
        summaries["message_intel"] = message_intel
    pump_tracker = panel_summaries.summarize_pump_tracker_guarded()
    if pump_tracker:
        summaries["pump_tracker"] = pump_tracker
    pump_ladder = panel_summaries.summarize_pump_ladder_guarded()
    if pump_ladder:
        summaries["pump_ladder"] = pump_ladder
    dev_signals = panel_summaries.summarize_dev_signals_guarded()
    if dev_signals:
        summaries["dev_signals"] = dev_signals
    pump_desk_snapshots = panel_summaries.summarize_pump_desk_snapshots_guarded()
    if pump_desk_snapshots:
        summaries["pump_desk_snapshots"] = pump_desk_snapshots

    try:
        from internal.council.selector_scheduler import get_selector_scheduler_state
        from internal.council.resolver_scheduler import get_prediction_resolver_scheduler_state

        schedulers = {
            "prediction_resolver": get_prediction_resolver_scheduler_state(),
            "selector_rotation": get_selector_scheduler_state(),
        }
    except Exception:
        schedulers = {}

    payload = {
        "status": "success",
        "trail": trail,
        "trail_count": len(trail),
        "event_type_counts": event_type_counts(trail),
        "summaries": summaries,
        "schedulers": schedulers,
        "integration_status": _build_integration_status(),
    }
    _STATE_CACHE["at"] = now
    _STATE_CACHE["payload"] = payload
    return payload


def get_stale_mindmap_state() -> Optional[Dict[str, Any]]:
    """Last-good state payload for timeout fallback (any age)."""
    cached = _STATE_CACHE.get("payload")
    if isinstance(cached, dict):
        return dict(cached)
    return None
