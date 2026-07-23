"""Pump desk learning step 1 — frozen pump_lead claims at ladder phase entry.

Grades on the shared resolver clock (predictions.json). Never nudges council
expert weights — resolver skips learning hooks when pick_source=pump_lead.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from internal.learning.predictions_store import append_prediction, load_predictions

logger = logging.getLogger(__name__)

PUMP_LEAD_CLAIM_PCT = 2.0
PUMP_LEAD_HORIZON_HOURS = 1
_JUST_STARTED_MAX_SCORE = 0.72
_LEAD_PHASES = frozenset({"STIRRING", "ACCUMULATING"})


def _just_started_max() -> float:
    try:
        from internal.learning.pump_calibration import effective_lead_gates

        return float(effective_lead_gates()["just_started_max_score"])
    except Exception:
        return _JUST_STARTED_MAX_SCORE


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _badge_for_entry(phase: str, score: float) -> str:
    phase = phase.upper()
    if phase == "STIRRING":
        return "WARMING UP"
    if phase == "ACCUMULATING":
        return "BUILDING"
    if phase == "PUMPING" and score < _just_started_max():
        return "JUST STARTED"
    return phase


def gradeable_phase_entry(phase: str, score: float) -> Optional[str]:
    """Return ledger claim label when this phase entry should be recorded."""
    phase = str(phase or "").upper()
    if phase in _LEAD_PHASES:
        return phase
    if phase == "PUMPING" and score < _just_started_max():
        return "JUST_STARTED"
    return None


def has_pending_pump_lead(netuid: Any) -> bool:
    try:
        nu = int(netuid)
    except (TypeError, ValueError):
        return False
    for row in load_predictions().get("predictions") or []:
        if not isinstance(row, dict):
            continue
        if row.get("status") != "pending":
            continue
        if str(row.get("pick_source") or "").lower() != "pump_lead":
            continue
        if row.get("netuid") == nu:
            return True
    return False


def record_pump_lead_at_phase_entry(
    *,
    netuid: Any,
    name: Optional[str],
    phase: str,
    composite_score: float,
    reference_price: float,
    signal_snapshot: Optional[Dict[str, Any]] = None,
    alert_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Persist a gradeable pump_lead row when the ladder enters a lead phase."""
    claim = gradeable_phase_entry(phase, composite_score)
    if not claim:
        return None
    try:
        nu = int(netuid)
    except (TypeError, ValueError):
        return None
    # Root / invalid — never training samples
    if nu < 1:
        return None
    ref = float(reference_price or 0)
    if ref <= 0:
        return None
    if has_pending_pump_lead(nu):
        return None

    now = _utcnow()
    resolve_at = now + timedelta(hours=PUMP_LEAD_HORIZON_HOURS)
    badge = _badge_for_entry(phase, composite_score)
    frozen = dict(signal_snapshot) if isinstance(signal_snapshot, dict) else {}

    # Quality gate — don't ledger placeholder-flow STIRRING noise
    try:
        from internal.learning.pump_lead_recover import sample_quality_ok

        probe = {
            "netuid": nu,
            "reference_price": ref,
            "pump_phase": str(phase).upper(),
            "pump_badge": badge,
            "pump_claim": claim,
            "signal_snapshot": frozen,
            "pick_source": "pump_lead",
        }
        ok, reason = sample_quality_ok(probe)
        if not ok:
            logger.debug("pump_lead skip SN%s: %s", nu, reason)
            return None
    except Exception:
        pass

    prediction: Dict[str, Any] = {
        "id": uuid.uuid4().hex[:10],
        "netuid": nu,
        "name": name or f"SN{nu}",
        "direction": "up",
        "predicted_pct": PUMP_LEAD_CLAIM_PCT,
        "horizon_hours": PUMP_LEAD_HORIZON_HOURS,
        "horizon_type": "pump_lead",
        "reference_price": ref,
        "created_at": now.isoformat().replace("+00:00", "Z"),
        "resolve_at": resolve_at.isoformat().replace("+00:00", "Z"),
        "status": "pending",
        "pick_source": "pump_lead",
        "pump_phase": str(phase).upper(),
        "pump_badge": badge,
        "pump_claim": claim,
        "composite_score": float(composite_score),
        "signal_snapshot": frozen,
        "statement": f"pump lead +{PUMP_LEAD_CLAIM_PCT:.0f}% within 1h from {badge} entry",
    }
    if alert_id:
        prediction["alert_id"] = str(alert_id)
    try:
        from internal.learning.pump_lead_features import attach_frozen_features

        attach_frozen_features(
            prediction,
            signal_snapshot=frozen,
            composite_score=float(composite_score),
        )
    except Exception as exc:
        logger.debug("pump_lead feature freeze skipped SN%s: %s", nu, exc)
    if not append_prediction(prediction):
        return None
    logger.info("pump_lead ledger: SN%s %s @ %.6f", nu, badge, ref)
    try:
        from internal.learning.pump_phase_notify import maybe_notify_pump_phase_entry

        maybe_notify_pump_phase_entry(
            netuid=nu,
            name=name,
            badge=badge,
            phase=phase,
        )
    except Exception:
        pass
    return prediction
