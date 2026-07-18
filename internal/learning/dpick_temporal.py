"""K3-4 — temporal confidence fields for daily_pick / dossier ring."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _pick_prediction(payload: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None
    for key in ("pick", "candidate"):
        block = payload.get(key)
        if not isinstance(block, dict):
            continue
        pred = block.get("prediction")
        if isinstance(pred, dict) and pred.get("resolve_at"):
            return pred
    return None


def _format_remaining(delta_seconds: float) -> str:
    if delta_seconds <= 0:
        return "0m"
    total_min = int(delta_seconds // 60)
    hours, minutes = divmod(total_min, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def ring_state_for(
    resolve_at: Optional[datetime],
    created_at: Optional[datetime],
    *,
    outcome_resolved: bool = False,
    horizon_hours: float = 4.0,
) -> str:
    if outcome_resolved:
        return "resolved"
    if resolve_at is None:
        return "fresh"
    now = datetime.now(timezone.utc)
    if now >= resolve_at:
        return "resolved"
    if created_at is not None:
        total = (resolve_at - created_at).total_seconds()
    else:
        total = max(horizon_hours, 0.25) * 3600.0
    if total <= 0:
        return "expiring"
    remaining = (resolve_at - now).total_seconds()
    frac = remaining / total
    if frac >= 0.5:
        return "fresh"
    if frac >= 0.25:
        return "aging"
    return "expiring"


def build_temporal_block(
    daily_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Derive temporal fields from embedded pick prediction (honest-empty when thin)."""
    payload = daily_payload if isinstance(daily_payload, dict) else {}
    pred = _pick_prediction(payload)
    outcome = str(payload.get("outcome_status") or "pending").lower()
    resolved = outcome == "resolved"

    if not pred:
        return {
            "resolve_at": None,
            "time_horizon": payload.get("horizon") or "24h",
            "resolves_in": None,
            "temporal_badge": None,
            "ring_state": "resolved" if resolved else "fresh",
            "grade_on_resolve": True,
        }

    resolve_at = _parse_dt(pred.get("resolve_at"))
    created_at = _parse_dt(pred.get("created_at"))
    try:
        horizon_hours = float(pred.get("horizon_hours") or 4)
    except (TypeError, ValueError):
        horizon_hours = 4.0
    horizon_label = f"{int(horizon_hours)}h" if horizon_hours == int(horizon_hours) else f"{horizon_hours:.1f}h"

    state = ring_state_for(
        resolve_at,
        created_at,
        outcome_resolved=resolved,
        horizon_hours=horizon_hours,
    )

    if resolve_at is None:
        return {
            "resolve_at": None,
            "time_horizon": horizon_label,
            "resolves_in": None,
            "temporal_badge": None,
            "ring_state": state,
            "grade_on_resolve": True,
        }

    now = datetime.now(timezone.utc)
    remaining = max(0.0, (resolve_at - now).total_seconds())
    resolves_in = _format_remaining(remaining)

    if state == "resolved":
        badge = "RESOLVED · graded on close"
    else:
        badge = f"LIVE · {resolves_in} remaining"

    return {
        "resolve_at": resolve_at.isoformat().replace("+00:00", "Z"),
        "time_horizon": horizon_label,
        "resolves_in": resolves_in,
        "temporal_badge": badge,
        "ring_state": state,
        "grade_on_resolve": True,
    }


def attach_temporal_to_daily_pick(
    daily_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    base = dict(daily_payload) if isinstance(daily_payload, dict) else {}
    try:
        temporal = build_temporal_block(base)
        base.update(temporal)
        if temporal.get("resolve_at"):
            base["horizon"] = temporal.get("time_horizon") or base.get("horizon") or "24h"
    except Exception as exc:
        logger.warning("dpick temporal attach failed: %s", exc)
    return base
