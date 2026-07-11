"""Canonical cockpit section builders — shared contract for Agent B UI."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

SECTION_IDS: tuple[str, ...] = (
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
    "judges": "Judge Council",
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


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _summary_text(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
        sentences = value.get("sentences")
        if isinstance(sentences, list):
            joined = " ".join(str(s).strip() for s in sentences if s)
            if joined:
                return joined
    return ""


def _empty_summary(section_id: str) -> str:
    return (
        f"{SECTION_TITLES.get(section_id, section_id)} has no live data yet on this deploy. "
        "The panel will populate automatically once upstream schedulers and stores warm up."
    )


def _unavailable_summary(section_id: str, reason: str = "") -> str:
    detail = f" ({reason})" if reason else ""
    return (
        f"{SECTION_TITLES.get(section_id, section_id)} is temporarily unavailable{detail}. "
        "This is an honest degraded state — not a placeholder summary."
    )


def _section(
    section_id: str,
    *,
    summary: str,
    metrics: Optional[Dict[str, Any]] = None,
    status: str = "live",
    updated_at: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "id": section_id,
        "title": SECTION_TITLES.get(section_id, section_id.replace("_", " ").title()),
        "summary": summary,
        "metrics": metrics or {},
        "status": status,
        "updated_at": updated_at or _utcnow_z(),
    }


def _build_council_picks() -> Dict[str, Any]:
    from internal.learning.panel_summaries import summarize_picks

    raw = summarize_picks()
    text = _summary_text(raw)
    metrics: Dict[str, Any] = {}
    try:
        from fetchers.taomarketcap import get_all_subnets
        from internal.council.daily_pick_engine import get_or_create_today_pick
        from internal.council.hourly_pick import select_hourly_pick
        from internal.council.weights import load_weights

        subnets = get_all_subnets() or []
        ctx = {"tao_change_24h": 0.0, "weights": load_weights()}
        hour_pick = select_hourly_pick(subnets, ctx) if subnets else {}
        daily = get_or_create_today_pick(subnets, ctx)
        metrics = {
            "hour_pick_netuid": (hour_pick.get("subnet") or {}).get("netuid"),
            "daily_action": daily.get("action") if isinstance(daily, dict) else None,
            "subnet_count": len(subnets),
        }
        status = "live" if subnets else "empty"
    except Exception:
        status = "live" if text else "empty"
    if not text:
        return _section("council_picks", summary=_empty_summary("council_picks"), status="empty")
    return _section("council_picks", summary=text, metrics=metrics, status=status)


def _build_judges() -> Dict[str, Any]:
    from internal.learning.panel_summaries import summarize_judges

    raw = summarize_judges()
    text = _summary_text(raw)
    metrics: Dict[str, Any] = {}
    try:
        from internal.judges.portfolios import _load as load_portfolios

        data = load_portfolios()
        for name in ("oracle", "echo", "pulse"):
            block = data.get(name) or {}
            summary = block.get("summary") or {}
            metrics[f"{name}_win_pct"] = summary.get("win_pct", 0)
            metrics[f"{name}_open"] = summary.get("open_positions", 0)
        status = "live" if any(metrics.values()) else "empty"
    except Exception:
        status = "live" if text else "empty"
    if not text:
        return _section("judges", summary=_empty_summary("judges"), status="empty")
    return _section("judges", summary=text, metrics=metrics, status=status)


def _build_learning_loop() -> Dict[str, Any]:
    from internal.learning.panel_summaries import summarize_learning

    raw = summarize_learning()
    text = _summary_text(raw)
    metrics: Dict[str, Any] = {}
    try:
        from internal.council import resolver
        from internal.council.weights import load_weights

        stats = (resolver.get_resolved_predictions().get("stats") or {})
        metrics = {
            "correct": stats.get("correct", 0),
            "wrong": stats.get("wrong", 0),
            "pending": stats.get("pending", 0),
            "accuracy": stats.get("accuracy", 0.0),
            "top_expert": max(load_weights().items(), key=lambda kv: float(kv[1] or 0))[0]
            if load_weights()
            else None,
        }
        status = "live" if int(stats.get("correct", 0) or 0) + int(stats.get("wrong", 0) or 0) > 0 else "empty"
    except Exception:
        status = "live" if text else "empty"
    if not text:
        return _section("learning_loop", summary=_empty_summary("learning_loop"), status="empty")
    return _section("learning_loop", summary=text, metrics=metrics, status=status)


def _build_predictions() -> Dict[str, Any]:
    from internal.council import resolver
    from internal.learning.predictions_store import load_predictions, update_stats

    data = load_predictions()
    update_stats(data)
    stats = data.get("stats") or {}
    pending = data.get("predictions") or []
    resolved = data.get("resolved") or []
    resolved_stats = (resolver.get_resolved_predictions().get("stats") or {})

    correct = int(resolved_stats.get("correct", stats.get("correct", 0)) or 0)
    wrong = int(resolved_stats.get("wrong", stats.get("wrong", 0)) or 0)
    pending_n = int(stats.get("pending", len(pending)) or 0)
    accuracy = float(resolved_stats.get("accuracy", stats.get("accuracy", 0)) or 0)

    metrics = {
        "pending": pending_n,
        "resolved": len(resolved),
        "correct": correct,
        "wrong": wrong,
        "accuracy": accuracy,
    }

    if not pending and not resolved:
        return _section(
            "predictions",
            summary=(
                "No predictions are queued or resolved yet. Hour and day pick endpoints enqueue "
                "new rows on the next Council cycle; the resolver scheduler grades due picks "
                "against live prices so outcomes feed the learning loop."
            ),
            metrics=metrics,
            status="empty",
        )

    summary = (
        f"The prediction store holds {pending_n} pending and {len(resolved)} resolved forecasts "
        f"({correct} correct, {wrong} wrong, {accuracy * 100:.1f}% accuracy). "
        "Due picks are graded automatically by the resolver scheduler and nudge expert weights "
        "on each hit or miss."
    )
    return _section("predictions", summary=summary, metrics=metrics, status="live")


def _build_scenario_memory() -> Dict[str, Any]:
    from internal.analytics.scenario_summary import summarize_scenario
    from internal.council import scenario_memory

    snap = scenario_memory.get_memory_snapshot()
    text = _summary_text(summarize_scenario(snap))
    scenarios = snap.get("scenarios") or []
    stats = snap.get("stats") or {}
    metrics = {
        "scenario_count": len(scenarios),
        "dominant_regime": max((stats.get("by_regime") or {}).items(), key=lambda kv: kv[1])[0]
        if stats.get("by_regime")
        else None,
        "last_updated": (snap.get("meta") or {}).get("last_updated"),
    }
    status = "live" if scenarios else "empty"
    if not text:
        text = _empty_summary("scenario_memory")
    return _section("scenario_memory", summary=text, metrics=metrics, status=status)


def _build_pump_ladder() -> Dict[str, Any]:
    from internal.pump.summary import summarize_pump
    from internal.pump.state import get_ladder_snapshot

    raw = summarize_pump()
    text = _summary_text(raw)
    snap = get_ladder_snapshot()
    meta = snap.get("meta") or {}
    metrics = {
        "tracked_subnets": meta.get("tracked_subnets", len(snap.get("subnets") or [])),
        "phase_counts": meta.get("phase_counts") or {},
        "last_scan_at": meta.get("last_scan_at"),
    }
    tracked = int(metrics["tracked_subnets"] or 0)
    status = "live" if tracked > 0 else "empty"
    if not text:
        text = _empty_summary("pump_ladder")
    return _section("pump_ladder", summary=text, metrics=metrics, status=status)


def _build_pump_tracker() -> Dict[str, Any]:
    from internal.pump_tracker.adapter import live_stats
    from internal.pump_tracker.summary import summarize_pump_tracker

    raw = summarize_pump_tracker()
    text = _summary_text(raw)
    stats = live_stats()
    if not stats.get("ok"):
        return _section(
            "pump_tracker",
            summary=text or _unavailable_summary("pump_tracker", str(stats.get("error", ""))),
            metrics={"error": stats.get("error")},
            status="unavailable",
        )
    metrics = {
        "total_subnets": stats.get("total_subnets", 0),
        "phase_counts": stats.get("phase_counts") or {},
        "source": stats.get("source"),
    }
    status = "live" if int(stats.get("total_subnets") or 0) > 0 else "empty"
    if not text:
        text = _empty_summary("pump_tracker")
    return _section("pump_tracker", summary=text, metrics=metrics, status=status)


def _build_trace() -> Dict[str, Any]:
    from internal.trace.store import load_store
    from internal.trace.summary import summarize_trace

    store = load_store()
    records = store.get("records") or []
    text = summarize_trace(store)
    metrics = {
        "record_count": len(records),
        "last_updated": (store.get("meta") or {}).get("last_updated"),
    }
    status = "live" if records else "empty"
    if not text:
        text = _empty_summary("trace")
    return _section("trace", summary=text, metrics=metrics, status=status)


def _build_message_intel() -> Dict[str, Any]:
    from internal.message_intel.sources import source_status
    from internal.message_intel.store import live_stats
    from internal.message_intel.summary import summarize_message_intel

    raw = summarize_message_intel()
    text = _summary_text(raw)
    stats = live_stats()
    if not stats.get("ok"):
        return _section(
            "message_intel",
            summary=text or _unavailable_summary("message_intel", str(stats.get("error", ""))),
            metrics={"sources": source_status()},
            status="unavailable",
        )
    metrics = {
        "total_messages": stats.get("total_messages", 0),
        "high_conviction_count": stats.get("high_conviction_count", 0),
        "channels": len(stats.get("channels") or []),
    }
    status = "live" if int(stats.get("total_messages") or 0) > 0 else "empty"
    if not text:
        text = _empty_summary("message_intel")
    return _section("message_intel", summary=text, metrics=metrics, status=status)


def _build_mindmap_trail() -> Dict[str, Any]:
    from internal.learning.mindmap_aggregator import collect_trail_events, event_type_counts

    trail = collect_trail_events(limit=50)
    counts = event_type_counts(trail)
    metrics = {
        "trail_count": len(trail),
        "event_type_counts": counts,
    }
    if not trail:
        return _section(
            "mindmap_trail",
            summary=(
                "Mindmap trail is empty — no signal, pick, resolve, or rotation events have "
                "been recorded yet. As Council picks, predictions resolve, and pump phases "
                "transition, rows append here and mirror into Soul-Map."
            ),
            metrics=metrics,
            status="empty",
        )
    latest = trail[0]
    summary = (
        f"The mindmap trail holds {len(trail)} recent events across "
        f"{sum(1 for c in counts.values() if c)} event types. "
        f"The latest entry is {latest.get('event_type', 'unknown')} "
        f"for {latest.get('subnet') or latest.get('netuid') or 'the fleet'} "
        f"at {latest.get('time', 'recently')}."
    )
    return _section("mindmap_trail", summary=summary, metrics=metrics, status="live")


def _build_rotation() -> Dict[str, Any]:
    try:
        from fetchers.taomarketcap import get_all_subnets
        from internal.council import rotation_tracker
        from internal.council.rotation_tokens import build_rotation_tokens_response

        subnets = get_all_subnets() or []
        rot = rotation_tracker.get_rotation_summary(subnets)
        tokens_resp = build_rotation_tokens_response()
    except Exception as exc:
        return _section(
            "rotation",
            summary=_unavailable_summary("rotation", str(exc)),
            status="unavailable",
        )

    patterns = rot.get("patterns") or []
    tokens = tokens_resp.get("tokens") or []
    metrics = {
        "pattern_count": len(patterns),
        "token_count": len(tokens),
        "top_pattern": patterns[0].get("name") if patterns else None,
    }
    if not patterns and not tokens:
        return _section(
            "rotation",
            summary=(
                "Rotation watchlists have not detected actionable patterns yet. "
                "Subnet volatility clusters and external rotation-token prices will "
                "populate once TaoMarketCap subnets and CoinGecko feeds respond."
            ),
            metrics=metrics,
            status="empty",
        )
    parts = []
    if patterns:
        top = patterns[0]
        parts.append(
            f"Top rotation pattern: {top.get('name')} ({top.get('count', 0)} subnets, "
            f"confidence {float(top.get('confidence', 0)):.2f})."
        )
    if tokens:
        movers = sorted(
            [t for t in tokens if t.get("price_change_24h") is not None],
            key=lambda t: abs(float(t.get("price_change_24h") or 0)),
            reverse=True,
        )
        if movers:
            lead = movers[0]
            parts.append(
                f"Leading rotation token {lead.get('symbol')} is "
                f"{float(lead.get('price_change_24h', 0)):+.1f}% over 24h."
            )
    parts.append(
        f"Tracker scanned {len(subnets)} subnets and {len(tokens)} external rotation tokens."
    )
    return _section("rotation", summary=" ".join(parts), metrics=metrics, status="live")


def _build_soul_map() -> Dict[str, Any]:
    try:
        from internal.council.weights import _load_raw

        data = _load_raw()
        sms = data.get("soul_map_state") or {}
        decisions = (sms.get("last_selector_output") or {}).get("decisions") or []
        trail_len = len(sms.get("learning_trail") or [])
        updated_at = sms.get("updated_at")
    except Exception as exc:
        return _section(
            "soul_map",
            summary=_unavailable_summary("soul_map", str(exc)),
            status="unavailable",
        )

    accum = sum(1 for d in decisions if d.get("recommended_action") == "accumulate")
    reduce = sum(1 for d in decisions if d.get("recommended_action") == "reduce")
    hold = len(decisions) - accum - reduce
    metrics = {
        "decision_count": len(decisions),
        "accumulate": accum,
        "reduce": reduce,
        "hold": hold,
        "trail_rows": trail_len,
        "updated_at": updated_at,
    }

    if not decisions:
        return _section(
            "soul_map",
            summary=(
                "Soul-Map dispositions are not populated yet. The daily selector rotation "
                "will write accumulate / hold / reduce decisions per subnet and mirror "
                "learning-trail rows as picks resolve."
            ),
            metrics=metrics,
            status="empty",
            updated_at=updated_at or _utcnow_z(),
        )

    summary = (
        f"Soul-Map tracks {len(decisions)} subnet dispositions: {accum} accumulate, "
        f"{hold} hold, and {reduce} reduce. "
        f"The learning trail holds {trail_len} rows linking picks, resolves, and pump transitions."
    )
    return _section(
        "soul_map",
        summary=summary,
        metrics=metrics,
        status="live",
        updated_at=updated_at or _utcnow_z(),
    )


_BUILDERS: Dict[str, Callable[[], Dict[str, Any]]] = {
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


def _safe_section(section_id: str) -> Dict[str, Any]:
    builder = _BUILDERS.get(section_id)
    if builder is None:
        return _section(
            section_id,
            summary=_unavailable_summary(section_id, "unknown section id"),
            status="unavailable",
        )
    try:
        row = builder()
        row.setdefault("id", section_id)
        row.setdefault("title", SECTION_TITLES.get(section_id, section_id))
        row.setdefault("summary", _empty_summary(section_id))
        row.setdefault("metrics", {})
        row.setdefault("status", "empty")
        row.setdefault("updated_at", _utcnow_z())
        return row
    except Exception as exc:
        logger.warning("cockpit section %s failed: %s", section_id, exc)
        return _section(
            section_id,
            summary=_unavailable_summary(section_id, str(exc)),
            status="unavailable",
        )


def get_cockpit_section(section_id: str) -> Dict[str, Any]:
    """Return one cockpit section card (never raises)."""
    key = str(section_id or "").strip().lower()
    if key not in SECTION_IDS:
        return _section(
            key or "unknown",
            summary=f"Unknown cockpit section {section_id!r}.",
            status="unavailable",
        )
    return _safe_section(key)


def get_cockpit_sections() -> Dict[str, Any]:
    """Return all 12 cockpit sections — canonical schema for Agent B UI."""
    sections = [_safe_section(section_id) for section_id in SECTION_IDS]
    return {"status": "success", "sections": sections}
