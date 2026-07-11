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
    STATE_PATH,
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


def load_state(path: str = STATE_PATH) -> Dict[str, Any]:
    with _lock:
        data = safe_read_json(path, default={})
        if not isinstance(data, dict):
            return {"version": "1.0", "subnets": {}, "meta": {}}
        data.setdefault("subnets", {})
        data.setdefault("meta", {})
        return data


def save_state(data: Dict[str, Any], path: str = STATE_PATH) -> None:
    with _lock:
        safe_write_json(path, data)


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

    entry["name"] = signals.get("name") or entry.get("name")
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


def get_ladder_snapshot(path: str = STATE_PATH) -> Dict[str, Any]:
    data = load_state(path)
    subnets = list((data.get("subnets") or {}).values())
    subnets.sort(key=lambda s: float(s.get("composite_score") or 0), reverse=True)
    return {
        "status": "success",
        "meta": data.get("meta") or {},
        "subnets": subnets,
        "count": len(subnets),
    }


def classify_subnet_row(subnet: Dict[str, Any]) -> Dict[str, Any]:
    """Classify a single subnet dict without persisting (for tests)."""
    signals = build_subnet_signals(subnet)
    return classify_signals(signals)
