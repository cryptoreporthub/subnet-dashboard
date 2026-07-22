"""Per-subnet pump ladder state machine with hysteresis + persistence."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from internal.file_utils import safe_read_json, safe_write_json
from internal.pump.constants import (
    PHASE_EXIT_THRESHOLDS,
    PHASE_INDEX,
    PHASE_LOCK_MINUTES,
    PHASE_ORDER,
)
from internal.pump.engine import classify_signals
from internal.pump.signals import build_subnet_signals, fetch_all_subnet_signals
from internal.pump.soul_sync import apply_phase_transitions

logger = logging.getLogger(__name__)

_lock = threading.RLock()


def _now_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _minutes_between(a: Optional[str], b: datetime) -> float:
    start = _parse_ts(a)
    if start is None:
        return 0.0
    return max(0.0, (b - start).total_seconds() / 60.0)


def _resolve_path(path: Optional[str] = None) -> str:
    if path:
        return path
    from internal.pump.constants import STATE_PATH as _path

    return _path


def load_state(path: Optional[str] = None) -> Dict[str, Any]:
    resolved = _resolve_path(path)
    with _lock:
        data = safe_read_json(resolved, default={})
        if not isinstance(data, dict):
            return {"version": "1.0", "subnets": {}, "meta": {}}
        data.setdefault("subnets", {})
        data.setdefault("meta", {})
        return data


def save_state(data: Dict[str, Any], path: Optional[str] = None) -> None:
    resolved = _resolve_path(path)
    with _lock:
        safe_write_json(resolved, data)


def _apply_hysteresis(
    current: str,
    suggested: str,
    score: float,
    since: Optional[str],
    now: datetime,
) -> str:
    """Prevent flapping: respect lock window and exit thresholds."""
    if current == suggested:
        return current

    locked = _minutes_between(since, now) < PHASE_LOCK_MINUTES
    if current != "DORMANT" and locked and suggested != "COOLING":
        return current

    cur_idx = PHASE_INDEX.get(current, 0)
    sug_idx = PHASE_INDEX.get(suggested, 0)

    # Downward moves allowed when score crosses exit band.
    if sug_idx < cur_idx:
        exit_threshold = PHASE_EXIT_THRESHOLDS.get(current)
        if exit_threshold is not None and score >= exit_threshold:
            return current
        return suggested

    # Upward: allow at most +1 phase per tick unless coming from DORMANT.
    if current == "DORMANT":
        return suggested
    if sug_idx > cur_idx + 1:
        return PHASE_ORDER[min(cur_idx + 1, len(PHASE_ORDER) - 1)]
    return suggested


def transition_subnet(
    state: Dict[str, Any],
    signals: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> Tuple[Optional[Dict[str, Any]], bool]:
    """Update one subnet entry; returns (transition_event, changed)."""
    now = now or datetime.now(timezone.utc)
    netuid = signals.get("netuid")
    if netuid is None:
        return None, False

    key = str(netuid)
    subnets = state.setdefault("subnets", {})
    entry = subnets.get(key) or {
        "netuid": netuid,
        "name": signals.get("name"),
        "phase": "DORMANT",
        "since": _now_z(),
        "composite_score": 0.0,
        "transitions": [],
    }

    classification = classify_signals(signals, current_phase=entry.get("phase", "DORMANT"))
    score = classification["composite_score"]
    suggested = classification["suggested_phase"]
    current = entry.get("phase", "DORMANT")
    new_phase = _apply_hysteresis(current, suggested, score, entry.get("since"), now)

    changed = new_phase != current
    if changed:
        transition = {
            "time": _now_z(),
            "from_phase": current,
            "to_phase": new_phase,
            "composite_score": score,
            "signals": classification.get("signals"),
        }
        transitions = entry.setdefault("transitions", [])
        transitions.append(transition)
        entry["transitions"] = transitions[-50:]
        entry["phase"] = new_phase
        entry["since"] = _now_z()
        entry["last_transition"] = _now_z()
        try:
            from internal.learning.pump_lead_ledger import record_pump_lead_at_phase_entry

            sig = classification.get("signals") if isinstance(classification.get("signals"), dict) else signals
            if isinstance(sig, dict) and "triad" not in sig:
                from internal.pump.triad import attach_triad_to_signals

                sig = attach_triad_to_signals(sig)
            record_pump_lead_at_phase_entry(
                netuid=netuid,
                name=entry.get("name"),
                phase=new_phase,
                composite_score=score,
                reference_price=float(sig.get("price") or signals.get("price") or 0),
                signal_snapshot=sig,
            )
        except Exception as exc:
            logger.debug("pump_lead ledger skipped SN%s: %s", netuid, exc)

    raw_name = signals.get("name") or entry.get("name")
    try:
        from internal.subnet_names import resolve_subnet_name

        entry["name"] = resolve_subnet_name(int(netuid), tmc_name=raw_name, use_taostats=False)
    except Exception:
        entry["name"] = raw_name
    entry["composite_score"] = score
    entry["updated_at"] = _now_z()
    entry["signal_snapshot"] = classification.get("signals")
    subnets[key] = entry

    return (
        {
            "netuid": netuid,
            "name": entry.get("name"),
            "from_phase": current,
            "to_phase": new_phase,
            "composite_score": score,
        }
        if changed
        else None,
        changed,
    )


def scan_all_subnets(state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Scan ~129 subnets, apply ladder transitions, persist + Soul-Map/trail."""
    with _lock:
        data = state if state is not None else load_state()
        signal_rows = fetch_all_subnet_signals()
        if not signal_rows:
            return {"ok": False, "error": "no subnet signals", "scanned": 0, "transitions": []}

        transitions: List[Dict[str, Any]] = []
        for row in signal_rows:
            event, changed = transition_subnet(data, row)
            if changed and event:
                transitions.append(event)

        data.setdefault("meta", {})
        data["meta"]["last_scan_at"] = _now_z()
        data["meta"]["tracked_subnets"] = len(data.get("subnets", {}))
        data["meta"]["last_transition_count"] = len(transitions)

        phase_counts: Dict[str, int] = {p: 0 for p in PHASE_ORDER}
        for entry in data.get("subnets", {}).values():
            phase_counts[str(entry.get("phase", "DORMANT"))] = phase_counts.get(
                str(entry.get("phase", "DORMANT")), 0
            ) + 1
        data["meta"]["phase_counts"] = phase_counts

        save_state(data)
        soul = apply_phase_transitions(transitions, data)

        return {
            "ok": True,
            "scanned": len(signal_rows),
            "transitions": transitions,
            "phase_counts": phase_counts,
            "soul_map": soul,
        }


def get_ladder_snapshot(path: Optional[str] = None) -> Dict[str, Any]:
    return _build_ladder_payload(path)


def get_ladder(path: Optional[str] = None) -> Dict[str, Any]:
    """Public alias imported by ``internal.pump_tracker.adapter``."""
    return get_ladder_snapshot(path)


def build_ladder_snapshot(path: Optional[str] = None) -> Dict[str, Any]:
    """Alias of ``get_ladder_snapshot`` (Agent B adapter import name)."""
    return get_ladder_snapshot(path)


def _normalize_ladder_subnet(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Shape persisted state rows for pump-tracker read API consumers."""
    phase = str(entry.get("phase") or entry.get("current_phase") or "DORMANT").upper()
    score = float(entry.get("composite_score") or 0.0)
    netuid = entry.get("netuid")
    return {
        "netuid": netuid,
        "name": entry.get("name") or f"SN{netuid}",
        "current_phase": phase,
        "phase": phase,
        "composite_score": score,
        "pump_score": score,
        "final_score": score,
        "pump_proneness": round(score * 100, 1),
        "re_pump_prob": 0.0,
        "since": entry.get("since"),
        "updated_at": entry.get("updated_at"),
        "last_transition": entry.get("last_transition"),
        "transitions": entry.get("transitions") or [],
    }


def _build_ladder_payload(path: Optional[str] = None) -> Dict[str, Any]:
    data = load_state(path)
    subnets_raw = [
        entry for entry in (data.get("subnets") or {}).values() if isinstance(entry, dict)
    ]
    subnets = [_normalize_ladder_subnet(entry) for entry in subnets_raw]
    subnets.sort(key=lambda s: float(s.get("composite_score") or 0), reverse=True)
    meta = dict(data.get("meta") or {})
    meta.setdefault("total_subnets", len(subnets))
    meta.setdefault("tracked_subnets", len(subnets))
    meta.setdefault("updated_at", meta.get("last_scan_at"))
    return {
        "status": "success",
        "source": "internal.pump.state",
        "meta": meta,
        "subnets": subnets,
        "count": len(subnets),
    }


def get_top_movers(limit: int = 20, path: Optional[str] = None) -> Dict[str, Any]:
    """Recent phase transitions from persisted ladder state (graceful empty list)."""
    data = load_state(path)
    rows: List[Dict[str, Any]] = []
    for entry in (data.get("subnets") or {}).values():
        if not isinstance(entry, dict):
            continue
        netuid = entry.get("netuid")
        name = entry.get("name") or f"SN{netuid}"
        for tx in entry.get("transitions") or []:
            if not isinstance(tx, dict):
                continue
            from_phase = tx.get("from_phase")
            to_phase = tx.get("to_phase")
            if not from_phase or not to_phase or from_phase == to_phase:
                continue
            max_score = float(tx.get("composite_score") or entry.get("composite_score") or 0.0)
            rows.append(
                {
                    "netuid": netuid,
                    "name": name,
                    "from_phase": from_phase,
                    "to_phase": to_phase,
                    "max_score": max_score,
                    "transition_at": tx.get("time"),
                }
            )
    rows.sort(key=lambda row: float(row.get("max_score") or 0.0), reverse=True)
    movers = rows[: max(0, int(limit))]
    return {
        "status": "success",
        "source": "internal.pump.state",
        "count": len(movers),
        "movers": movers,
    }


def classify_subnet_row(subnet: Dict[str, Any]) -> Dict[str, Any]:
    """Classify a single subnet dict without persisting (for tests)."""
    signals = build_subnet_signals(subnet)
    return classify_signals(signals)
