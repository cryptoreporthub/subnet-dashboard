"""Phase L consumer — social verdicts → alerts (no rules-engine edits)."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_SUBNET_RE = re.compile(r"\b(\d{1,3})\b")


def _first_netuid(analysis: Dict[str, Any]) -> Optional[int]:
    entities = analysis.get("entities") if isinstance(analysis, dict) else {}
    subnets = entities.get("subnets") if isinstance(entities, dict) else []
    for raw in subnets or []:
        m = _SUBNET_RE.search(str(raw))
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                continue
    return None


def emit_social_alert_if_needed(
    message_id: int,
    payload: Dict[str, Any],
    verdict: Dict[str, Any],
    analysis: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Create a Phase L alert for high-conviction social messages."""
    try:
        conviction = float(verdict.get("conviction") or 0)
    except (TypeError, ValueError):
        conviction = 0.0
    if conviction < 60:
        return None

    source = str(payload.get("source") or "telegram")
    group_id = str(payload.get("group_id") or "")
    ext_id = str(payload.get("message_id") or message_id)
    dedupe_key = f"social:{source}:{group_id}:{ext_id}"
    verdict_label = str(verdict.get("verdict") or "neutral")
    severity = "warning" if verdict_label == "bearish" else "info"
    if conviction >= 80 and verdict_label == "bearish":
        severity = "critical"

    snippet = str(payload.get("content") or "")[:120]
    try:
        from internal.signals.alerts import AlertEngine

        return AlertEngine().create_alert(
            {
                "alert_type": "social_intel",
                "message": f"Social {verdict_label} ({conviction:.0f}% conv): {snippet}",
                "severity": severity,
                "subnet_id": _first_netuid(analysis),
                "dedupe_key": dedupe_key,
                "details": {
                    "message_id": message_id,
                    "source": source,
                    "group_id": group_id,
                    "external_message_id": ext_id,
                },
            }
        )
    except Exception as exc:
        logger.warning("social alert emit skipped for message %s: %s", message_id, exc)
        return None
