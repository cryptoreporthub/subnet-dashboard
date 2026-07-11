"""Read-model adapter — prefers Agent A ``internal.pump`` engine, hardened legacy fallback."""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from internal.pump import constants
from internal.pump.constants import PHASE_ORDER

logger = logging.getLogger(__name__)

VALID_PHASES = frozenset(PHASE_ORDER)
DEFAULT_PHASE = "DORMANT"


class PumpEngineUnavailable(Exception):
    """Raised when neither Agent A pump engine nor legacy tracker is available."""


def _engine_source() -> str:
    try:
        from internal.pump import state as pump_state  # noqa: F401

        if hasattr(pump_state, "get_ladder_snapshot"):
            return "internal.pump.state"
    except ImportError:
        pass
    return "legacy_tracker"


def _iter_subnet_rows(container: Any) -> List[Dict[str, Any]]:
    """Coerce list-or-dict subnet containers into dict rows."""
    if container is None:
        return []
    if isinstance(container, dict):
        rows: List[Dict[str, Any]] = []
        for key, value in container.items():
            if isinstance(value, dict):
                row = dict(value)
                row.setdefault("netuid", value.get("netuid", key))
                rows.append(row)
            elif isinstance(key, (int, str)) and str(key).isdigit():
                rows.append({"netuid": int(key), "name": f"SN{key}", "phase": str(value)})
        return rows
    if isinstance(container, list):
        rows = []
        for item in container:
            if isinstance(item, dict):
                rows.append(item)
        return rows
    return []


def _subnet_phase(row: Dict[str, Any]) -> str:
    phase = row.get("current_phase") or row.get("phase") or DEFAULT_PHASE
    return str(phase).upper()


def _normalize_ladder_payload(payload: Dict[str, Any], *, source: str) -> Dict[str, Any]:
    subnets_in = _iter_subnet_rows(payload.get("subnets"))
    subnets_out: List[Dict[str, Any]] = []
    for row in subnets_in:
        phase = _subnet_phase(row)
        subnets_out.append(
            {
                "netuid": row.get("netuid"),
                "name": row.get("name") or f"SN{row.get('netuid')}",
                "symbol": row.get("symbol"),
                "current_phase": phase,
                "phase": phase,
                "phase_duration_minutes": row.get("phase_duration_minutes")
                or row.get("duration_min"),
                "composite_score": row.get("composite_score", row.get("final_score", 0.0)),
                "pump_score": row.get("pump_score", row.get("composite_score", 0.0)),
                "final_score": row.get("final_score", row.get("composite_score", 0.0)),
                "pump_proneness": row.get("pump_proneness", 0),
                "re_pump_prob": row.get("re_pump_prob", 0.0),
                "since": row.get("since"),
                "updated_at": row.get("updated_at"),
            }
        )
    meta = dict(payload.get("meta") or {})
    meta.setdefault("total_subnets", len(subnets_out))
    return {
        "status": payload.get("status", "success"),
        "source": source,
        "subnets": subnets_out,
        "meta": meta,
        "count": len(subnets_out),
    }


def _engine_ladder_snapshot() -> Optional[Dict[str, Any]]:
    """Prefer Agent A ladder APIs in documented hotfix order."""
    try:
        from internal.pump.state import get_ladder

        payload = get_ladder(constants.STATE_PATH)
        if isinstance(payload, dict) and payload.get("subnets") is not None:
            return _normalize_ladder_payload(payload, source="internal.pump.state")
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("internal.pump.state.get_ladder failed: %s", exc)

    try:
        from internal.pump.state import get_ladder_snapshot as agent_get_ladder_snapshot

        payload = agent_get_ladder_snapshot(constants.STATE_PATH)
        if isinstance(payload, dict):
            return _normalize_ladder_payload(payload, source="internal.pump.state")
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("internal.pump.state.get_ladder_snapshot failed: %s", exc)

    try:
        from internal.pump.engine import build_ladder_snapshot

        payload = build_ladder_snapshot()
        if isinstance(payload, dict):
            return _normalize_ladder_payload(payload, source="internal.pump.engine")
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("internal.pump.engine.build_ladder_snapshot failed: %s", exc)

    return None


def _engine_top_movers(limit: int) -> Optional[Dict[str, Any]]:
    try:
        from internal.pump.engine import get_top_movers as agent_top_movers

        payload = agent_top_movers(limit=limit)
        if isinstance(payload, dict):
            movers = _iter_subnet_rows(payload.get("movers"))
            if not movers and isinstance(payload.get("movers"), list):
                movers = [m for m in payload["movers"] if isinstance(m, dict)]
            return {
                "status": payload.get("status", "success"),
                "source": "internal.pump.engine",
                "count": min(limit, len(movers)),
                "movers": movers[:limit],
            }
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("internal.pump.engine.get_top_movers failed: %s", exc)

    try:
        from internal.pump.state import load_state

        data = load_state(constants.STATE_PATH)
        scored: List[Dict[str, Any]] = []
        for entry in _iter_subnet_rows(data.get("subnets")):
            netuid = entry.get("netuid")
            for transition in entry.get("transitions") or []:
                if not isinstance(transition, dict):
                    continue
                start = str(transition.get("from_phase", DEFAULT_PHASE))
                end = str(transition.get("to_phase", DEFAULT_PHASE))
                if start == end:
                    continue
                scored.append(
                    {
                        "netuid": netuid,
                        "name": entry.get("name"),
                        "from_phase": start,
                        "to_phase": end,
                        "transition_at": transition.get("time"),
                        "max_score": transition.get("composite_score", 0.0),
                        "composite_score": transition.get("composite_score", 0.0),
                    }
                )
        scored.sort(key=lambda row: float(row.get("composite_score") or 0.0), reverse=True)
        return {
            "status": "success",
            "source": "internal.pump.state",
            "count": min(limit, len(scored)),
            "movers": scored[:limit],
        }
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("internal.pump.state transition scan failed: %s", exc)

    return None


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
            return [r for r in rows if isinstance(r, dict)]
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

    analytics = tracker.get_all_analytics() if hasattr(tracker, "get_all_analytics") else {}
    if not isinstance(analytics, dict):
        analytics = {}

    analytics_rows: Dict[Any, Dict[str, Any]] = {}
    for row in _iter_subnet_rows((analytics.get("data") or {}).get("subnets")):
        uid = row.get("netuid")
        if uid is None:
            continue
        analytics_rows[uid] = row
        analytics_rows[str(uid)] = row

    phases_raw = tracker.get_current_phases() if hasattr(tracker, "get_current_phases") else {}
    phase_by_uid: Dict[Any, Dict[str, Any]] = {}
    if isinstance(phases_raw, dict):
        for key, value in phases_raw.items():
            if isinstance(value, dict):
                uid = value.get("netuid", key)
                phase_by_uid[uid] = value
                phase_by_uid[str(uid)] = value
            elif isinstance(key, (int, str)):
                phase_by_uid[key] = {"phase": DEFAULT_PHASE, "netuid": key}
                phase_by_uid[str(key)] = phase_by_uid[key]

    subnets_out: List[Dict[str, Any]] = []
    for sn in _load_subnets():
        uid = sn.get("netuid")
        if uid is None:
            continue
        row = analytics_rows.get(uid) or analytics_rows.get(str(uid)) or {}
        phase_state = phase_by_uid.get(uid) or phase_by_uid.get(str(uid)) or {}
        phase = _subnet_phase({**row, **phase_state})
        subnets_out.append(
            {
                "netuid": uid,
                "name": sn.get("name") or row.get("name") or f"SN{uid}",
                "symbol": sn.get("symbol"),
                "current_phase": phase,
                "phase": phase,
                "phase_duration_minutes": row.get("phase_duration_minutes")
                or phase_state.get("duration_min"),
                "pump_score": float(row.get("pump_score") or 0.0),
                "final_score": float(row.get("final_score") or 0.0),
                "pump_proneness": int(row.get("pump_proneness") or 0),
                "re_pump_prob": float(row.get("re_pump_prob") or 0.0),
            }
        )

    if not subnets_out and analytics_rows:
        seen: set = set()
        for uid, row in analytics_rows.items():
            if not isinstance(row, dict):
                continue
            netuid = row.get("netuid", uid)
            key = (netuid, str(netuid))
            if key in seen:
                continue
            seen.add(key)
            phase = _subnet_phase(row)
            subnets_out.append(
                {
                    "netuid": netuid,
                    "name": row.get("name", f"SN{netuid}"),
                    "current_phase": phase,
                    "phase": phase,
                    "phase_duration_minutes": row.get("phase_duration_minutes", 0.0),
                    "pump_score": float(row.get("pump_score") or 0.0),
                    "final_score": float(row.get("final_score") or 0.0),
                    "pump_proneness": int(row.get("pump_proneness") or 0),
                    "re_pump_prob": float(row.get("re_pump_prob") or 0.0),
                }
            )

    meta = (analytics.get("data") or {}).get("meta") if isinstance(analytics.get("data"), dict) else {}
    if not isinstance(meta, dict):
        meta = {}
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
        "count": len(subnets_out),
    }


def get_ladder_snapshot() -> Dict[str, Any]:
    """All subnets with current pump ladder phase."""
    engine_payload = _engine_ladder_snapshot()
    if engine_payload is not None:
        return engine_payload
    return _legacy_ladder()


def subnets_for_phase(phase: str) -> Dict[str, Any]:
    phase_key = str(phase or "").upper()
    if phase_key not in VALID_PHASES:
        return {
            "status": "error",
            "error": f"Unknown phase {phase!r}; expected one of {list(PHASE_ORDER)}",
            "phase": phase_key,
            "count": 0,
            "subnets": [],
        }
    ladder = get_ladder_snapshot()
    rows = [
        row
        for row in _iter_subnet_rows(ladder.get("subnets"))
        if _subnet_phase(row) == phase_key
    ]
    return {
        "status": "success",
        "source": ladder.get("source", _engine_source()),
        "phase": phase_key,
        "count": len(rows),
        "subnets": rows,
    }


def _legacy_top_movers(limit: int) -> Dict[str, Any]:
    from internal.pump_tracker.core import get_pump_tracker

    tracker = get_pump_tracker()
    if tracker is None:
        raise PumpEngineUnavailable("pump engine unavailable")

    cycles_raw = tracker.get_recent_cycles(limit=200) if hasattr(tracker, "get_recent_cycles") else []
    cycle_rows: Iterable[Any]
    if isinstance(cycles_raw, dict):
        cycle_rows = cycles_raw.values()
    elif isinstance(cycles_raw, list):
        cycle_rows = cycles_raw
    else:
        cycle_rows = []

    scored: List[Dict[str, Any]] = []
    for cycle in cycle_rows:
        if not isinstance(cycle, dict):
            continue
        start = str(cycle.get("start_phase", DEFAULT_PHASE))
        end = str(cycle.get("end_phase", DEFAULT_PHASE))
        if start == end:
            continue
        scored.append(
            {
                "netuid": cycle.get("netuid"),
                "from_phase": start,
                "to_phase": end,
                "transition_at": cycle.get("end"),
                "max_score": float(cycle.get("max_score") or 0.0),
                "duration_min": float(cycle.get("duration_min") or 0.0),
            }
        )
    scored.sort(key=lambda row: float(row.get("max_score") or 0.0), reverse=True)
    return {
        "status": "success",
        "source": "legacy_tracker",
        "count": min(limit, len(scored)),
        "movers": scored[:limit],
    }


def get_top_movers(limit: int = 20) -> Dict[str, Any]:
    engine_payload = _engine_top_movers(limit)
    if engine_payload is not None:
        return engine_payload
    return _legacy_top_movers(limit)


def live_stats() -> Dict[str, Any]:
    """Aggregate counters for summaries."""
    try:
        ladder = get_ladder_snapshot()
    except PumpEngineUnavailable as exc:
        return {"ok": False, "error": str(exc)}

    from collections import Counter

    phases: Counter[str] = Counter()
    for row in _iter_subnet_rows(ladder.get("subnets")):
        phases[_subnet_phase(row)] += 1

    try:
        movers = get_top_movers(limit=5)
    except PumpEngineUnavailable:
        movers = {"movers": []}

    return {
        "ok": True,
        "source": ladder.get("source"),
        "total_subnets": len(_iter_subnet_rows(ladder.get("subnets"))),
        "phase_counts": dict(phases),
        "meta": ladder.get("meta") or {},
        "top_movers": movers.get("movers") or [],
    }
