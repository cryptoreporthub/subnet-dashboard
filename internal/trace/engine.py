"""Trace lineage engine — signal→decision records with Soul-Map + trail integration."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.trace.store import append_record, load_store

logger = logging.getLogger(__name__)

SIGNAL_TYPES = (
    "message_intel",
    "pump_phase",
    "scenario_tag",
    "soul_map_disposition",
    "weight_change",
    "judge_signal",
    "pick_signal",
)


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _new_trace_id() -> str:
    return f"tr_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"


def _normalize_signals(signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for sig in signals:
        if not isinstance(sig, dict):
            continue
        sig_type = str(sig.get("type") or sig.get("signal_type") or "unknown")
        out.append(
            {
                "type": sig_type,
                "source": sig.get("source") or sig_type,
                "payload": sig.get("payload") or {k: v for k, v in sig.items() if k not in {"type", "signal_type", "source", "payload"}},
            }
        )
    return out


def _update_soul_map_lineage(record: Dict[str, Any], store_path: Optional[str] = None) -> None:
    """Mirror trace stats into Soul-Map (merged save, preserves weights)."""
    try:
        from internal.council.mindmap_bridge import MindmapBridge
        from internal.council.weights import SOUL_MAP_PATH

        store = load_store(path=store_path)
        records = store.get("records") or []
        signal_counts: Dict[str, int] = {}
        for row in records:
            for sig in row.get("signals") or []:
                st = str(sig.get("type", "unknown"))
                signal_counts[st] = signal_counts.get(st, 0) + 1

        bridge = MindmapBridge(persistence_path=SOUL_MAP_PATH)
        bridge.soul_map_state["decision_lineage"] = {
            "last_record": record,
            "total_records": len(records),
            "top_signal_types": sorted(
                signal_counts.items(), key=lambda kv: kv[1], reverse=True
            )[:6],
            "updated_at": _utcnow_z(),
        }
        bridge._save_to_disk()
    except Exception as exc:
        logger.warning("Soul-Map lineage mirror failed: %s", exc)


def _emit_lineage_trail(record: Dict[str, Any]) -> None:
    """Emit conviction_update or signal_triggered via existing trail bus (call-only)."""
    try:
        from internal.learning.trail_bus import emit_conviction_update, emit_signal_triggered
    except Exception as exc:
        logger.warning("Trail bus import failed: %s", exc)
        return

    signals = record.get("signals") or []
    decision = record.get("decision") or {}
    decision_type = record.get("decision_type", "decision")
    subnet = record.get("subnet")
    netuid = record.get("netuid")

    primary = signals[0] if signals else {}
    primary_type = str(primary.get("type", "lineage"))

    if primary_type in {"pump_phase", "message_intel"} or decision_type == "signal_chain":
        emit_signal_triggered(
            subnet=subnet,
            netuid=netuid,
            signal_name=f"trace_{primary_type}",
            direction=str(decision.get("action") or decision.get("direction") or decision_type),
            evidence={
                "trace_id": record.get("id"),
                "signals": signals,
                "decision": decision,
                "decision_type": decision_type,
            },
        )
    else:
        emit_conviction_update(
            subnet=subnet,
            netuid=netuid,
            conviction=decision.get("conviction") or decision.get("confidence"),
            horizon_type=decision.get("horizon_type"),
            evidence={
                "trace_id": record.get("id"),
                "signals": signals,
                "decision": decision,
                "decision_type": decision_type,
            },
        )


def record_lineage(
    *,
    decision_type: str,
    decision: Dict[str, Any],
    signals: List[Dict[str, Any]],
    subnet: Optional[str] = None,
    netuid: Optional[Any] = None,
    store_path: Optional[str] = None,
    emit_trail: bool = True,
    update_soul_map: bool = True,
) -> Dict[str, Any]:
    """Persist a signal→decision lineage row and integrate with Soul-Map + trail."""
    record: Dict[str, Any] = {
        "id": _new_trace_id(),
        "created_at": _utcnow_z(),
        "decision_type": decision_type,
        "decision": decision,
        "signals": _normalize_signals(signals),
        "subnet": subnet,
        "netuid": netuid,
    }
    append_record(record, path=store_path)
    if update_soul_map:
        _update_soul_map_lineage(record, store_path=store_path)
    if emit_trail:
        _emit_lineage_trail(record)
    return record
