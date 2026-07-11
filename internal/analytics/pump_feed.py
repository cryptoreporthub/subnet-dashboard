"""Pump trail subscriber — emits ladder phase / signal events from live tracker state."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from internal.analytics.trail_cursor import last_pump_phases, save_pump_phases

logger = logging.getLogger(__name__)

_TRAIL_PHASES = {"EARLY", "SELL", "SECOND_WIND", "EXHAUSTING"}


def _emit_pump_signal(subnet: Dict[str, Any], old_phase: str, new_phase: str) -> None:
    try:
        from internal.learning.trail_events import emit_trail_event
    except Exception as exc:
        logger.warning("Could not import trail emitter: %s", exc)
        return

    netuid = subnet.get("netuid")
    name = subnet.get("name") or f"SN{netuid}"
    event_type = "signal_triggered" if new_phase in {"EARLY", "SELL"} else "pump_phase"

    emit_trail_event(
        event_type,
        subnet=name,
        netuid=netuid,
        evidence={
            "pump_phase": new_phase,
            "previous_phase": old_phase,
            "pump_score": subnet.get("pump_score"),
            "final_score": subnet.get("final_score"),
            "pump_proneness": subnet.get("pump_proneness"),
            "re_pump_prob": subnet.get("re_pump_prob"),
        },
        signal=f"pump_{new_phase.lower()}",
        decision="phase_transition",
    )


def sync_pump_trail_events(pump_payload: Dict[str, Any] | None = None) -> int:
    """Detect pump phase transitions and emit trail events.

    Accepts ``get_all_analytics()`` payload or fetches live tracker state.
    Returns count of events emitted.
    """
    if pump_payload is None:
        try:
            from internal.pump_tracker import get_pump_tracker

            tracker = get_pump_tracker()
            pump_payload = tracker.get_all_analytics() if tracker else {"data": {"subnets": []}}
        except Exception as exc:
            logger.warning("Pump trail sync skipped: %s", exc)
            return 0

    subnets: List[Dict[str, Any]] = (pump_payload.get("data") or {}).get("subnets") or []
    previous = last_pump_phases()
    current: Dict[str, str] = {}
    emitted = 0

    for row in subnets:
        netuid = row.get("netuid")
        if netuid is None:
            continue
        key = str(netuid)
        new_phase = str(row.get("current_phase", "INACTIVE"))
        current[key] = new_phase
        old_phase = previous.get(key, "INACTIVE")
        if old_phase == new_phase:
            continue
        if new_phase not in _TRAIL_PHASES and old_phase == "INACTIVE":
            continue
        if new_phase in _TRAIL_PHASES or (old_phase != "INACTIVE" and new_phase != old_phase):
            _emit_pump_signal(row, old_phase, new_phase)
            emitted += 1

    save_pump_phases(current)
    return emitted
