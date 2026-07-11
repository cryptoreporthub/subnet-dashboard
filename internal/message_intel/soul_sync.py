"""Soul-Map disposition updates + Mindmap trail for message-intel signals."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from internal.council.weights import SOUL_MAP_PATH as _DEFAULT_SOUL_MAP_PATH
from internal.learning.trail_bus import (
    emit_conviction_update,
    emit_disposition_shift,
    emit_signal_triggered,
)

logger = logging.getLogger(__name__)


def _soul_map_path() -> str:
    from internal.council import weights

    return getattr(weights, "SOUL_MAP_PATH", _DEFAULT_SOUL_MAP_PATH)


def _now_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _extract_netuids(analysis: Dict[str, Any]) -> List[int]:
    entities = analysis.get("entities") or {}
    subnets = entities.get("subnets") or []
    found: List[int] = []
    for token in subnets:
        for num in re.findall(r"\d+", str(token)):
            try:
                found.append(int(num))
            except ValueError:
                continue
    return sorted(set(found))


def _action_from_verdict(verdict: Dict[str, Any]) -> str:
    label = str(verdict.get("verdict", "neutral")).lower()
    if label == "bullish":
        return "accumulate"
    if label == "bearish":
        return "reduce"
    return "hold"


def apply_batch_to_soul_map(
    *,
    batch_size: int,
    records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Merge message-intel batch into Soul-Map and emit trail events."""
    if not records:
        return {"disposition_updates": 0, "trail_events": 0}

    try:
        from internal.council.mindmap_bridge import MindmapBridge
    except Exception as exc:
        logger.warning("MindmapBridge unavailable for message-intel: %s", exc)
        return {"disposition_updates": 0, "trail_events": 0, "error": str(exc)}

    bridge = MindmapBridge(persistence_path=_soul_map_path())
    sms = bridge.soul_map_state
    intel_meta = sms.setdefault("message_intel", {})
    intel_meta["last_batch_at"] = _now_z()
    intel_meta["last_batch_size"] = batch_size
    intel_meta["total_batches"] = int(intel_meta.get("total_batches", 0)) + 1

    log = sms.setdefault("message_intel_log", [])
    dispositions = sms.setdefault("message_intel_dispositions", {})
    disposition_updates = 0
    trail_events = 0

    for row in records:
        message_id = row.get("message_id")
        analysis = row.get("analysis") or {}
        verdict = row.get("verdict") or {}
        payload = row.get("payload") or {}
        content = str(payload.get("content") or "")[:200]
        source = payload.get("source") or "unknown"
        group = payload.get("group_name") or payload.get("group_id") or source

        log.append(
            {
                "message_id": message_id,
                "source": source,
                "group": group,
                "sentiment": analysis.get("sentiment"),
                "hype_score": analysis.get("hype_score"),
                "substance_score": analysis.get("substance_score"),
                "verdict": verdict.get("verdict"),
                "conviction": verdict.get("conviction"),
                "timestamp": _now_z(),
                "preview": content,
            }
        )

        action = _action_from_verdict(verdict)
        conviction = float(verdict.get("conviction") or 0)
        netuids = _extract_netuids(analysis)

        for netuid in netuids:
            key = str(netuid)
            prior = dispositions.get(key) or {}
            old_action = prior.get("recommended_action")
            if old_action != action:
                disposition_updates += 1
                emit_disposition_shift(
                    netuid=netuid,
                    from_action=old_action,
                    to_action=action,
                    expert="message_intel",
                    evidence={
                        "message_id": message_id,
                        "source": source,
                        "conviction": conviction,
                        "sentiment": analysis.get("sentiment"),
                    },
                )
                trail_events += 1
            dispositions[key] = {
                "recommended_action": action,
                "conviction": conviction,
                "source": source,
                "updated_at": _now_z(),
                "message_id": message_id,
            }

            if conviction >= 60:
                emit_conviction_update(
                    netuid=netuid,
                    conviction=conviction,
                    evidence={
                        "message_id": message_id,
                        "source": source,
                        "verdict": verdict.get("verdict"),
                        "group": group,
                    },
                )
                trail_events += 1
            else:
                emit_signal_triggered(
                    netuid=netuid,
                    signal_name="message_intel",
                    direction=verdict.get("predicted_direction"),
                    evidence={
                        "message_id": message_id,
                        "source": source,
                        "sentiment": analysis.get("sentiment"),
                        "hype_score": analysis.get("hype_score"),
                    },
                )
                trail_events += 1

    sms["message_intel_log"] = log[-200:]
    sms["message_intel_dispositions"] = dispositions
    intel_meta["disposition_count"] = len(dispositions)
    bridge.soul_map_state = sms
    bridge._save_to_disk()

    emit_signal_triggered(
        signal_name="message_intel_batch",
        evidence={
            "batch_size": batch_size,
            "processed": len(records),
            "disposition_updates": disposition_updates,
            "sources": sorted({(r.get("payload") or {}).get("source") for r in records}),
        },
        direction="ingest",
    )
    trail_events += 1

    return {
        "disposition_updates": disposition_updates,
        "trail_events": trail_events,
        "disposition_count": len(dispositions),
    }
