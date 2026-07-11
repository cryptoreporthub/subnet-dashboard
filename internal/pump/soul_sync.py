"""Soul-Map pump dispositions + Mindmap trail on ladder transitions."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from internal.learning.trail_bus import emit_conviction_update, emit_signal_triggered
from internal.pump.constants import TRAIL_PHASES

logger = logging.getLogger(__name__)


def _now_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _soul_map_path() -> str:
    from internal.council import weights

    return getattr(weights, "SOUL_MAP_PATH", "data/soul_map.json")


def apply_phase_transitions(
    transitions: List[Dict[str, Any]],
    ladder_state: Dict[str, Any],
) -> Dict[str, Any]:
    if not transitions:
        return {"disposition_updates": 0, "trail_events": 0}

    try:
        from internal.council.mindmap_bridge import MindmapBridge
    except Exception as exc:
        logger.warning("MindmapBridge unavailable for pump ladder: %s", exc)
        return {"disposition_updates": 0, "trail_events": 0, "error": str(exc)}

    bridge = MindmapBridge(persistence_path=_soul_map_path())
    sms = bridge.soul_map_state
    pump_meta = sms.setdefault("pump_ladder", {})
    dispositions = sms.setdefault("pump_dispositions", {})
    log = sms.setdefault("pump_ladder_log", [])

    trail_events = 0
    disposition_updates = 0

    for tx in transitions:
        netuid = tx.get("netuid")
        name = tx.get("name") or f"SN{netuid}"
        to_phase = tx.get("to_phase")
        from_phase = tx.get("from_phase")
        score = float(tx.get("composite_score") or 0)

        key = str(netuid)
        prior = dispositions.get(key) or {}
        action_map = {
            "DORMANT": "hold",
            "STIRRING": "hold",
            "ACCUMULATING": "accumulate",
            "PUMPING": "accumulate",
            "COOLING": "reduce",
        }
        action = action_map.get(str(to_phase), "hold")
        dispositions[key] = {
            "recommended_action": action,
            "phase": to_phase,
            "composite_score": score,
            "updated_at": _now_z(),
        }
        disposition_updates += 1

        log.append(
            {
                "netuid": netuid,
                "name": name,
                "from_phase": from_phase,
                "to_phase": to_phase,
                "composite_score": score,
                "time": _now_z(),
            }
        )

        if str(to_phase) not in TRAIL_PHASES:
            continue

        if to_phase == "PUMPING" and score >= 0.65:
            emit_conviction_update(
                subnet=name,
                netuid=netuid,
                conviction=round(score * 100, 2),
                evidence={
                    "pump_phase": to_phase,
                    "previous_phase": from_phase,
                    "composite_score": score,
                },
            )
            trail_events += 1
        else:
            emit_signal_triggered(
                subnet=name,
                netuid=netuid,
                signal_name=f"pump_{str(to_phase).lower()}",
                direction=action,
                evidence={
                    "pump_phase": to_phase,
                    "previous_phase": from_phase,
                    "composite_score": score,
                },
            )
            trail_events += 1

    meta = ladder_state.get("meta") or {}
    pump_meta["last_batch_at"] = _now_z()
    pump_meta["phase_counts"] = meta.get("phase_counts") or {}
    pump_meta["tracked_subnets"] = meta.get("tracked_subnets", 0)
    sms["pump_ladder_log"] = log[-200:]
    sms["pump_dispositions"] = dispositions
    bridge.soul_map_state = sms
    bridge._save_to_disk()

    if transitions:
        emit_signal_triggered(
            signal_name="pump_ladder_scan",
            evidence={
                "transition_count": len(transitions),
                "phase_counts": meta.get("phase_counts"),
            },
            direction="scan_complete",
        )
        trail_events += 1

    return {
        "disposition_updates": disposition_updates,
        "trail_events": trail_events,
    }
