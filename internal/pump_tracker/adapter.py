"""Read-model adapter — prefers Agent A ``internal.pump`` engine, legacy fallback."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

VALID_PHASES = frozenset(
    {"INACTIVE", "EARLY", "EXHAUSTING", "CONSOLIDATING", "SECOND_WIND", "SELL"}
)


class PumpEngineUnavailable(Exception):
    """Raised when neither Agent A pump engine nor legacy tracker is available."""


def _engine_source() -> str:
    try:
        from internal.pump import state as pump_state  # noqa: F401

        if hasattr(pump_state, "get_ladder"):
            return "internal.pump.state"
    except ImportError:
        pass
    return "legacy_tracker"


def engine_available() -> bool:
    try:
        get_ladder_snapshot()
        return True
    except PumpEngineUnavailable:
        return False


def _load_subnets() -> List[Dict[str, Any]]:
    try:
        from fetchers.taomarketcap import get_all_subnets

        rows = get_all_subnets() or []
        if rows:
            return rows
    except Exception as exc:
        logger.warning("Subnet list for pump ladder failed: %s", exc)
    try:
        import json
        import os

        path = os.path.join("config", "registry.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fh:
                reg = json.load(fh)
            if isinstance(reg, dict):
                return [
                    {"netuid": int(k), "name": (v or {}).get("name", f"SN{k}")}
                    for k, v in reg.items()
                    if str(k).isdigit()
                ]
    except Exception:
        pass
    return []


def _legacy_ladder() -> Dict[str, Any]:
    from internal.pump_tracker.core import get_pump_tracker

    tracker = get_pump_tracker()
    if tracker is None:
        raise PumpEngineUnavailable("pump engine unavailable")

    analytics = tracker.get_all_analytics()
    analytics_rows = {
        row.get("netuid"): row
        for row in (analytics.get("data") or {}).get("subnets") or []
    }
    phases = tracker.get_current_phases()

    subnets_out: List[Dict[str, Any]] = []
    for sn in _load_subnets():
        uid = sn.get("netuid")
        if uid is None:
            continue
        row = analytics_rows.get(uid) or analytics_rows.get(str(uid)) or {}
        phase_state = phases.get(uid) or phases.get(str(uid)) or {}
        phase = str(row.get("current_phase") or phase_state.get("phase") or "INACTIVE")
        subnets_out.append(
            {
                "netuid": uid,
                "name": sn.get("name") or row.get("name") or f"SN{uid}",
                "symbol": sn.get("symbol"),
                "current_phase": phase,
                "phase_duration_minutes": row.get("phase_duration_minutes")
                or phase_state.get("duration_min"),
                "pump_score": row.get("pump_score", 0.0),
                "final_score": row.get("final_score", 0.0),
                "pump_proneness": row.get("pump_proneness", 0),
                "re_pump_prob": row.get("re_pump_prob", 0.0),
            }
        )

    if not subnets_out and analytics_rows:
        for uid, row in analytics_rows.items():
            subnets_out.append(
                {
                    "netuid": uid,
                    "name": row.get("name", f"SN{uid}"),
                    "current_phase": row.get("current_phase", "INACTIVE"),
                    "phase_duration_minutes": row.get("phase_duration_minutes", 0.0),
                    "pump_score": row.get("pump_score", 0.0),
                    "final_score": row.get("final_score", 0.0),
                    "pump_proneness": row.get("pump_proneness", 0),
                    "re_pump_prob": row.get("re_pump_prob", 0.0),
                }
            )

    meta = (analytics.get("data") or {}).get("meta") or {}
    return {
        "status": "success",
        "source": "legacy_tracker",
        "subnets": subnets_out,
        "meta": {
            "total_subnets": len(subnets_out),
            "tracked_subnets": meta.get("tracked_subnets", len(analytics_rows)),
            "total_cycles": meta.get("total_cycles", 0),
            "updated_at": meta.get("updated_at"),
        },
    }


def get_ladder_snapshot() -> Dict[str, Any]:
    """All subnets with current pump ladder phase."""
    try:
        from internal.pump.state import get_ladder

        payload = get_ladder()
        if isinstance(payload, dict) and payload.get("subnets") is not None:
            payload.setdefault("status", "success")
            payload.setdefault("source", "internal.pump.state")
            return payload
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("internal.pump.state.get_ladder failed: %s", exc)

    try:
        from internal.pump.engine import build_ladder_snapshot

        payload = build_ladder_snapshot()
        if isinstance(payload, dict):
            payload.setdefault("status", "success")
            payload.setdefault("source", "internal.pump.engine")
            return payload
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("internal.pump.engine.build_ladder_snapshot failed: %s", exc)

    return _legacy_ladder()


def subnets_for_phase(phase: str) -> Dict[str, Any]:
    phase_key = str(phase or "").upper()
    if phase_key not in VALID_PHASES:
        return {
            "status": "error",
            "error": f"Unknown phase {phase!r}; expected one of {sorted(VALID_PHASES)}",
            "phase": phase_key,
            "count": 0,
            "subnets": [],
        }
    ladder = get_ladder_snapshot()
    rows = [
        row
        for row in ladder.get("subnets") or []
        if str(row.get("current_phase", "INACTIVE")).upper() == phase_key
    ]
    return {
        "status": "success",
        "source": ladder.get("source", _engine_source()),
        "phase": phase_key,
        "count": len(rows),
        "subnets": rows,
    }


def get_top_movers(limit: int = 20) -> Dict[str, Any]:
    try:
        from internal.pump.engine import get_top_movers as agent_top_movers

        payload = agent_top_movers(limit=limit)
        if isinstance(payload, dict):
            payload.setdefault("status", "success")
            payload.setdefault("source", "internal.pump.engine")
            return payload
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("internal.pump.engine.get_top_movers failed: %s", exc)

    from internal.pump_tracker.core import get_pump_tracker

    tracker = get_pump_tracker()
    if tracker is None:
        raise PumpEngineUnavailable("pump engine unavailable")

    cycles = tracker.get_recent_cycles(limit=200)
    scored: List[Dict[str, Any]] = []
    for cycle in cycles:
        if not isinstance(cycle, dict):
            continue
        start = str(cycle.get("start_phase", "INACTIVE"))
        end = str(cycle.get("end_phase", "INACTIVE"))
        if start == end:
            continue
        scored.append(
            {
                "netuid": cycle.get("netuid"),
                "from_phase": start,
                "to_phase": end,
                "transition_at": cycle.get("end"),
                "max_score": cycle.get("max_score", 0.0),
                "duration_min": cycle.get("duration_min", 0.0),
            }
        )
    scored.sort(key=lambda row: float(row.get("max_score") or 0.0), reverse=True)
    return {
        "status": "success",
        "source": "legacy_tracker",
        "count": min(limit, len(scored)),
        "movers": scored[:limit],
    }


def live_stats() -> Dict[str, Any]:
    """Aggregate counters for summaries."""
    try:
        ladder = get_ladder_snapshot()
    except PumpEngineUnavailable as exc:
        return {"ok": False, "error": str(exc)}

    from collections import Counter

    phases: Counter[str] = Counter()
    for row in ladder.get("subnets") or []:
        phases[str(row.get("current_phase", "INACTIVE"))] += 1

    movers = get_top_movers(limit=5)
    return {
        "ok": True,
        "source": ladder.get("source"),
        "total_subnets": len(ladder.get("subnets") or []),
        "phase_counts": dict(phases),
        "meta": ladder.get("meta") or {},
        "top_movers": movers.get("movers") or [],
    }
