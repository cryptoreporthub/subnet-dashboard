"""Pump phase-entry push alerts (Wave 2 P4) — env-gated, rate-limited."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_ENABLED = frozenset({"1", "true", "on", "yes"})
_NOTIFY_BADGES = frozenset({"BUILDING", "JUST STARTED"})
_last_notify: Dict[int, float] = {}
_COOLDOWN_SEC = int(os.environ.get("PUMP_PHASE_NOTIFY_COOLDOWN_SEC", "3600"))


def pump_phase_alerts_enabled() -> bool:
    return os.environ.get("CONVICTION_ALERTS_ENABLED", "").lower() in _ENABLED


def maybe_notify_pump_phase_entry(
    *,
    netuid: Any,
    name: Optional[str],
    badge: str,
    phase: str,
    signal_snapshot: Optional[Dict[str, Any]] = None,
    composite_score: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Notify on BUILDING / JUST STARTED phase entry only. Default off."""
    if not pump_phase_alerts_enabled():
        return None
    badge_u = str(badge or "").upper()
    if badge_u not in _NOTIFY_BADGES:
        return None
    try:
        nu = int(netuid)
    except (TypeError, ValueError):
        return None

    now = time.time()
    last = _last_notify.get(nu, 0.0)
    if now - last < _COOLDOWN_SEC:
        return {"skipped": True, "reason": "rate_limited", "netuid": nu}

    from internal.learning.pump_alert import format_pump_phase_alert

    message = format_pump_phase_alert(
        netuid=nu,
        name=name,
        badge=badge_u,
        phase=str(phase or "").upper(),
        signal_snapshot=signal_snapshot,
        composite_score=composite_score,
    )
    alert = {
        "source": "pump_phase",
        "subnet_id": nu,
        "message": message,
        "dedupe_key": f"pump_phase:{nu}:{badge_u}",
        "details": {
            "badge": badge_u,
            "phase": phase,
            "name": name or f"SN{nu}",
            "signal_snapshot": signal_snapshot,
            "composite_score": composite_score,
        },
    }

    try:
        from internal.conviction_alerts.delivery import deliver_alerts

        result = deliver_alerts([alert])
    except Exception as exc:
        logger.warning("pump phase notify failed: %s", exc)
        return {"error": str(exc), "netuid": nu}

    _last_notify[nu] = now
    return {"notified": True, "netuid": nu, "delivery": result}
