"""Resolver backlog watchdog (Phase J1)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

PENDING_COUNT_THRESHOLD = 10
AGE_HORIZON_MULTIPLE = 2.0
_DEFAULT_HORIZON_HOURS = 24.0


def _parse_dt(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _horizon_hours(pred: Dict[str, Any]) -> float:
    try:
        horizon = float(pred.get("horizon_hours", 0) or 0)
    except (TypeError, ValueError):
        horizon = 0.0
    return horizon if horizon > 0 else _DEFAULT_HORIZON_HOURS


def check_resolver_watchdog(
    predictions: List[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    pending_threshold: int = PENDING_COUNT_THRESHOLD,
    age_horizon_multiple: float = AGE_HORIZON_MULTIPLE,
) -> Dict[str, Any]:
    """Warn when backlog size or pending rows survive past resolve grace."""
    now = now or datetime.now(timezone.utc)
    pending = [p for p in predictions if isinstance(p, dict)]
    oldest_age_hours = 0.0
    oldest_id: Any = None
    worst_overdue_hours = 0.0
    worst_threshold_hours = 0.0
    stale_id: Any = None

    for pred in pending:
        resolve_at = _parse_dt(pred.get("resolve_at"))
        created = _parse_dt(pred.get("created_at")) or resolve_at
        horizon = _horizon_hours(pred)
        grace_hours = horizon * age_horizon_multiple

        if created is not None:
            age_hours = (now - created).total_seconds() / 3600.0
            if age_hours > oldest_age_hours:
                oldest_age_hours = age_hours
                oldest_id = pred.get("id")

        if resolve_at is not None and now > resolve_at:
            overdue_hours = (now - resolve_at).total_seconds() / 3600.0
            if overdue_hours > grace_hours and overdue_hours > worst_overdue_hours:
                worst_overdue_hours = overdue_hours
                worst_threshold_hours = grace_hours
                stale_id = pred.get("id")
        elif created is not None and resolve_at is None:
            age_hours = (now - created).total_seconds() / 3600.0
            if age_hours > grace_hours and age_hours > worst_overdue_hours:
                worst_overdue_hours = age_hours
                worst_threshold_hours = grace_hours
                stale_id = pred.get("id")

    if stale_id is not None:
        return {
            "warning": True,
            "reason": "pending_past_grace",
            "pending_count": len(pending),
            "oldest_pending_age_hours": round(worst_overdue_hours, 2),
            "oldest_prediction_id": stale_id,
            "threshold_hours": round(worst_threshold_hours, 2),
        }

    if len(pending) > pending_threshold:
        return {
            "warning": True,
            "reason": "pending_count_exceeded",
            "pending_count": len(pending),
            "oldest_pending_age_hours": round(oldest_age_hours, 2),
            "oldest_prediction_id": oldest_id,
            "threshold_count": pending_threshold,
        }

    return {
        "warning": False,
        "pending_count": len(pending),
        "oldest_pending_age_hours": round(oldest_age_hours, 2),
        "oldest_prediction_id": oldest_id,
    }
