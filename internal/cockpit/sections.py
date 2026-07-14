"""Premium Cockpit section data layer — live summaries for all 12 dashboard panels."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

COCKPIT_SECTION_IDS: Tuple[str, ...] = (
    "council_picks",
    "judges",
    "learning_loop",
    "predictions",
    "scenario_memory",
    "pump_ladder",
    "pump_tracker",
    "trace",
    "message_intel",
    "mindmap_trail",
    "rotation",
    "soul_map",
)

SECTION_TITLES: Dict[str, str] = {
    "council_picks": "Council Picks",
    "judges": "Judges",
    "learning_loop": "Learning Loop",
    "predictions": "Predictions",
    "scenario_memory": "Scenario Memory",
    "pump_ladder": "Pump Ladder",
    "pump_tracker": "Pump Tracker",
    "trace": "Decision Trace",
    "message_intel": "Message Intel",
    "mindmap_trail": "Mindmap Trail",
    "rotation": "Rotation Tokens",
    "soul_map": "Soul Map",
}


def _now_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _summary_text(result: Any) -> str:
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, dict):
        text = str(result.get("text") or "").strip()
        if text:
            return text
        sentences = result.get("sentences") or []
        parts = [str(s).strip() for s in sentences if s and str(s).strip()]
        if parts:
            return " ".join(parts)
    return ""


def _empty_copy(section_id: str, reason: str, *, status: str = "empty") -> Dict[str, Any]:
    return {
        "id": section_id,
        "title": SECTION_TITLES[section_id],
        "summary": reason,
        "metrics": {},
        "status": status,
        "updated_at": _now_z(),
    }


def _live_section(
    section_id: str,
    summary: str,
    metrics: Dict[str, Any],
    *,
    updated_at: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "id": section_id,
        "title": SECTION_TITLES[section_id],
        "summary": summary or SECTION_TITLES[section_id] + " has no live summary yet.",
        "metrics": metrics or {},
        "status": "live",
        "updated_at": updated_at or _now_z(),
    }


def _build_council_picks() -> Dict[str, Any]:
    try:
        from internal.learning.panel_summaries import summarize_picks

        raw = summarize_picks()
        summary = _summary_text(raw)
        if not summary or "could not load" in summary.lower():
            return _empty_copy(
                "council_picks",
                summary
                or "Council hour and daily picks are not available from the current subnet snapshot.",
                status="empty" if summary else "unavailable",
            )
        return _live_section("council_picks", summary, {"sentences": len(raw.get("sentences") or [])})


    except Exception as _exc:
        logger.exception("cockpit section council_picks failed")
        return _empty_copy(
            "council_picks",
            f"{SECTION_TITLES['council_picks']} panel encountered an error: {_exc}",
            status="unavailable",
        )
def _build_judges() -> Dict[str, Any]:
    try:
        from internal.learning.panel_summaries import summarize_judges

        raw = summarize_judges()
        summary = _summary_text(raw)
        if "unavailable" in summary.lower():
            return _empty_copy("judges", summary, status="unavailable")
        return _live_section("judges", summary, {"judges": ("oracle", "echo", "pulse")})


    except Exception as _exc:
        logger.exception("cockpit section judges failed")
        return _empty_copy(
            "judges",
            f"{SECTION_TITLES['judges']} panel encountered an error: {_exc}",
            status="unavailable",
        )
def _build_learning_loop() -> Dict[str, Any]:
    try:
        from internal.council import resolver
        from internal.council.weights import load_weights
        from internal.learning.panel_summaries import summarize_learning

        raw = summarize_learning()
        summary = _summary_text(raw)
        stats = resolver.get_resolved_predictions().get("stats") or {}
        weights = load_weights()
        metrics = {
            "correct": int(stats.get("correct", 0) or 0),
            "wrong": int(stats.get("wrong", 0) or 0),
            "pending": int(stats.get("pending", 0) or 0),
            "accuracy": float(stats.get("accuracy", 0) or 0),
            "expert_count": len(weights or {}),
        }
        return _live_section("learning_loop", summary, metrics)


    except Exception as _exc:
        logger.exception("cockpit section learning_loop failed")
        return _empty_copy(
            "learning_loop",
            f"{SECTION_TITLES['learning_loop']} panel encountered an error: {_exc}",
            status="unavailable",
        )
def _build_predictions() -> Dict[str, Any]:
    try:
        from internal.council import resolver
        from internal.learning.predictions_store import load_predictions, update_stats

        pred_data = load_predictions()
        update_stats(pred_data)
        stats = pred_data.get("stats") or {}
        pending_list = [p for p in (pred_data.get("predictions") or []) if isinstance(p, dict)]
        resolved_stats = resolver.get_resolved_predictions().get("stats") or {}

        pending = int(stats.get("pending", resolved_stats.get("pending", 0)) or 0)
        correct = int(resolved_stats.get("correct", 0) or 0)
        wrong = int(resolved_stats.get("wrong", 0) or 0)
        total_resolved = int(resolved_stats.get("total", correct + wrong) or 0)

        if pending == 0 and total_resolved == 0 and not pending_list:
            return _empty_copy(
                "predictions",
                "No predictions are queued yet — hour and day pick endpoints will enqueue "
                "new rows when the Council publishes the next live rotation pick.",
            )

        parts = [
            f"The prediction store tracks {pending} pending call(s) with {total_resolved} "
            f"resolved ({correct} correct, {wrong} wrong).",
            "Each pick is graded by the resolver scheduler against live prices; outcomes "
            "feed expert weight nudges (+0.02 correct, −0.03 wrong).",
        ]
        if pending_list:
            latest = pending_list[0]
            parts.append(
                f"Latest pending: {latest.get('name') or 'unknown'} "
                f"{latest.get('direction', 'up')} — {latest.get('statement') or 'horizon pick queued'}."
            )
        else:
            parts.append("No pending rows remain; the next Council pick will seed fresh predictions.")

        return _live_section(
            "predictions",
            " ".join(parts[:4]),
            {
                "pending": pending,
                "resolved": total_resolved,
                "correct": correct,
                "wrong": wrong,
                "accuracy": float(resolved_stats.get("accuracy", 0) or 0),
            },
        )


    except Exception as _exc:
        logger.exception("cockpit section predictions failed")
        return _empty_copy(
            "predictions",
            f"{SECTION_TITLES['predictions']} panel encountered an error: {_exc}",
            status="unavailable",
        )
def _build_scenario_memory() -> Dict[str, Any]:
    try:
        from internal.analytics.scenario_summary import summarize_scenario
        from internal.analytics.scenario_state import load_scenario_snapshot

        snap = load_scenario_snapshot()
        scenarios = snap.get("scenarios") or []
        stats = snap.get("stats") or {}
        meta = snap.get("meta") or {}
        summary = summarize_scenario(snap)

        if not scenarios:
            return _empty_copy("scenario_memory", summary, status="empty")

        return _live_section(
            "scenario_memory",
            summary,
            {
                "total": int(stats.get("total") or len(scenarios)),
                "by_regime": stats.get("by_regime") or {},
                "last_updated": meta.get("last_updated"),
            },
            updated_at=str(meta.get("last_updated") or _now_z()),
        )


    except Exception as _exc:
        logger.exception("cockpit section scenario_memory failed")
        return _empty_copy(
            "scenario_memory",
            f"{SECTION_TITLES['scenario_memory']} panel encountered an error: {_exc}",
            status="unavailable",
        )
def _build_pump_ladder() -> Dict[str, Any]:
    try:
        from internal.pump.constants import PHASE_ORDER
        from internal.pump.state import get_ladder_snapshot
        from internal.pump.summary import summarize_pump

        raw = summarize_pump()
        summary = _summary_text(raw)
        snap = get_ladder_snapshot()
        meta = snap.get("meta") or {}
        phase_counts = meta.get("phase_counts") or {}
        tracked = int(meta.get("tracked_subnets") or len(snap.get("subnets") or []) or 0)

        if tracked == 0 and not summary:
            return _empty_copy(
                "pump_ladder",
                "The pump ladder has not scanned subnets yet; the boot scheduler will classify "
                "five-phase ladder rungs once registry data is available.",
            )

        metrics = {
            "tracked_subnets": tracked,
            "phase_counts": {p: int(phase_counts.get(p, 0)) for p in PHASE_ORDER},
            "last_scan_at": meta.get("last_scan_at"),
        }
        return _live_section(
            "pump_ladder",
            summary,
            metrics,
            updated_at=str(meta.get("last_scan_at") or _now_z()),
        )


    except Exception as _exc:
        logger.exception("cockpit section pump_ladder failed")
        return _empty_copy(
            "pump_ladder",
            f"{SECTION_TITLES['pump_ladder']} panel encountered an error: {_exc}",
            status="unavailable",
        )
def _build_pump_tracker() -> Dict[str, Any]:
    try:
        from internal.pump_tracker.adapter import live_stats
        from internal.pump_tracker.summary import summarize_pump_tracker

        raw = summarize_pump_tracker()
        summary = _summary_text(raw)
        stats = live_stats()
        if not stats.get("ok"):
            return _empty_copy(
                "pump_tracker",
                summary
                or "Pump tracker ladder is unavailable; endpoints degrade gracefully instead of returning 500.",
                status="unavailable",
            )

        total = int(stats.get("total_subnets") or 0)
        if total == 0:
            return _empty_copy(
                "pump_tracker",
                summary or "Pump-tracker ladder has no subnet rows yet.",
                status="empty",
            )

        return _live_section(
            "pump_tracker",
            summary,
            {
                "total_subnets": total,
                "phase_counts": stats.get("phase_counts") or {},
                "source": stats.get("source"),
            },
        )


    except Exception as _exc:
        logger.exception("cockpit section pump_tracker failed")
        return _empty_copy(
            "pump_tracker",
            f"{SECTION_TITLES['pump_tracker']} panel encountered an error: {_exc}",
            status="unavailable",
        )
def _build_trace() -> Dict[str, Any]:
    try:
        from internal.trace.store import load_store
        from internal.trace.summary import summarize_trace

        store = load_store()
        records = store.get("records") or []
        summary = summarize_trace(store)
        meta = store.get("meta") or {}

        if not records:
            return _empty_copy("trace", summary, status="empty")

        return _live_section(
            "trace",
            summary,
            {
                "record_count": len(records),
                "last_updated": meta.get("last_updated"),
            },
            updated_at=str(meta.get("last_updated") or _now_z()),
        )


    except Exception as _exc:
        logger.exception("cockpit section trace failed")
        return _empty_copy(
            "trace",
            f"{SECTION_TITLES['trace']} panel encountered an error: {_exc}",
            status="unavailable",
        )
def _build_message_intel() -> Dict[str, Any]:
    try:
        from internal.message_intel.sources import source_status
        from internal.message_intel.store import live_stats
        from internal.message_intel.summary import summarize_message_intel

        raw = summarize_message_intel()
        summary = _summary_text(raw)
        stats = live_stats()

        if not stats.get("ok"):
            return _empty_copy("message_intel", summary, status="unavailable")

        total = int(stats.get("total_messages") or 0)
        metrics = {
            "total_messages": total,
            "high_conviction_count": int(stats.get("high_conviction_count") or 0),
            "telegram_configured": bool(source_status().get("telegram", {}).get("configured")),
            "discord_configured": bool(source_status().get("discord", {}).get("configured")),
        }
        if total == 0:
            return _empty_copy("message_intel", summary, status="empty")

        return _live_section("message_intel", summary, metrics)


    except Exception as _exc:
        logger.exception("cockpit section message_intel failed")
        return _empty_copy(
            "message_intel",
            f"{SECTION_TITLES['message_intel']} panel encountered an error: {_exc}",
            status="unavailable",
        )
def _build_mindmap_trail() -> Dict[str, Any]:
    try:
        from internal.learning.mindmap_aggregator import collect_trail_events, event_type_counts

        trail = collect_trail_events(limit=25)
        counts = event_type_counts(trail)

        if not trail:
            return _empty_copy(
                "mindmap_trail",
                "The Mindmap learning trail is empty — pick, resolve, rotation, and scenario "
                "events will appear here as the Council loop runs.",
            )

        latest = trail[0]
        top_types = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:3]
        type_bits = ", ".join(f"{name} ({n})" for name, n in top_types if n)
        summary = (
            f"The learning trail holds {len(trail)} recent event(s); top types: {type_bits or 'none yet'}. "
            f"Latest: {latest.get('event_type', 'event')} on "
            f"{latest.get('subnet') or latest.get('netuid') or 'unknown'} "
            f"via {latest.get('signal') or 'signal'}. "
            "Trail rows merge Soul-Map persistence with derived prediction and scenario events."
        )

        return _live_section(
            "mindmap_trail",
            summary,
            {
                "trail_count": len(trail),
                "event_type_counts": counts,
                "latest_event_type": latest.get("event_type"),
            },
            updated_at=str(latest.get("time") or _now_z()),
        )


    except Exception as _exc:
        logger.exception("cockpit section mindmap_trail failed")
        return _empty_copy(
            "mindmap_trail",
            f"{SECTION_TITLES['mindmap_trail']} panel encountered an error: {_exc}",
            status="unavailable",
        )
def _build_rotation() -> Dict[str, Any]:
    try:
        from internal.council.rotation_tokens import build_rotation_tokens_response

        resp = build_rotation_tokens_response()
        tokens = resp.get("tokens") or []
        status = str(resp.get("status") or "ok")

        if status == "error" or not tokens:
            return _empty_copy(
                "rotation",
                "Rotation-token watchlist is empty or prices could not be fetched; "
                "CoinGecko-backed quotes populate this panel when the registry tokens resolve.",
                status="empty" if not tokens else "unavailable",
            )

        movers = sorted(tokens, key=lambda t: abs(float(t.get("change_24h") or 0)), reverse=True)
        leader = movers[0] if movers else {}
        parts = [
            f"Rotation watchlist tracks {len(tokens)} ecosystem tokens with live 24h price context.",
            f"Top mover: {leader.get('symbol') or leader.get('name') or 'unknown'} "
            f"({float(leader.get('change_24h') or 0):+.2f}% 24h).",
            "Snapshots mirror into Soul-Map and emit trail events when dispositions shift.",
        ]
        return _live_section(
            "rotation",
            " ".join(parts),
            {
                "token_count": len(tokens),
                "updated_at": resp.get("updated_at"),
            },
            updated_at=str(resp.get("updated_at") or _now_z()),
        )


    except Exception as _exc:
        logger.exception("cockpit section rotation failed")
        return _empty_copy(
            "rotation",
            f"{SECTION_TITLES['rotation']} panel encountered an error: {_exc}",
            status="unavailable",
        )
def _build_soul_map() -> Dict[str, Any]:
    try:
        from internal.council.weights import _load_raw

        data = _load_raw()
        sms = data.get("soul_map_state") or {}
        if not sms:
            return _empty_copy(
                "soul_map",
                "Soul-Map state has not been initialized yet; selector rotation and learning "
                "trail writes will populate dispositions on the next Council cycle.",
            )

        decisions = (sms.get("last_selector_output") or {}).get("decisions") or []
        trail = sms.get("learning_trail") or []
        accum = sum(1 for d in decisions if d.get("recommended_action") == "accumulate")
        reduce = sum(1 for d in decisions if d.get("recommended_action") == "reduce")
        hold = len(decisions) - accum - reduce
        updated_at = str(sms.get("updated_at") or _now_z())

        parts = [
            f"Soul-Map holds {len(trail)} persisted trail row(s) and "
            f"{len(decisions)} selector disposition(s).",
        ]
        if decisions:
            parts.append(
                f"Latest rotation snapshot: {accum} accumulate, {reduce} reduce, {hold} hold "
                "across tracked subnets."
            )
        else:
            parts.append("Daily selector rotation has not refreshed dispositions in this snapshot yet.")
        parts.append(
            "Message-intel, pump ladder, and trace modules mirror signal updates into this state."
        )

        return _live_section(
            "soul_map",
            " ".join(parts[:4]),
            {
                "trail_rows": len(trail),
                "disposition_count": len(decisions),
                "accumulate": accum,
                "reduce": reduce,
                "hold": hold,
            },
            updated_at=updated_at,
        )


    except Exception as _exc:
        logger.exception("cockpit section soul_map failed")
        return _empty_copy(
            "soul_map",
            f"{SECTION_TITLES['soul_map']} panel encountered an error: {_exc}",
            status="unavailable",
        )

_SECTION_BUILDERS: Dict[str, Callable[[], Dict[str, Any]]] = {
    "council_picks": _build_council_picks,
    "judges": _build_judges,
    "learning_loop": _build_learning_loop,
    "predictions": _build_predictions,
    "scenario_memory": _build_scenario_memory,
    "pump_ladder": _build_pump_ladder,
    "pump_tracker": _build_pump_tracker,
    "trace": _build_trace,
    "message_intel": _build_message_intel,
    "mindmap_trail": _build_mindmap_trail,
    "rotation": _build_rotation,
    "soul_map": _build_soul_map,
}


def _safe_build(section_id: str, builder: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    try:
        section = builder()
    except Exception as exc:
        logger.warning("cockpit section %s failed: %s", section_id, exc)
        return _empty_copy(
            section_id,
            f"{SECTION_TITLES[section_id]} is temporarily unavailable ({exc}). "
            "The dashboard will show this honest empty state instead of erroring.",
            status="unavailable",
        )

    section.setdefault("id", section_id)
    section.setdefault("title", SECTION_TITLES[section_id])
    section.setdefault("metrics", {})
    section.setdefault("updated_at", _now_z())
    if section.get("status") not in ("live", "empty", "unavailable"):
        section["status"] = "live" if section.get("summary") else "empty"
    return section


def get_cockpit_section(section_id: str) -> Dict[str, Any]:
    """Return one cockpit section by fixed id (for tests and partial refresh)."""
    if section_id not in _SECTION_BUILDERS:
        raise KeyError(f"Unknown cockpit section id: {section_id}")
    return _safe_build(section_id, _SECTION_BUILDERS[section_id])


def get_cockpit_sections() -> Dict[str, Any]:
    """Return all 12 cockpit sections conforming to the shared Premium Cockpit schema."""
    sections = [_safe_build(sid, _SECTION_BUILDERS[sid]) for sid in COCKPIT_SECTION_IDS]
    return {"status": "success", "sections": sections}
