"""Shared freshness and approval policy for supervised SimiVision bots.

This module is deliberately policy-only.  It does not persist approvals or
perform mutations; callers must send a proposed action to the appropriate
human review surface before executing it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional


# Upper bounds for each state.  ``stale`` is the last age bucket; an artifact
# older than that remains stale, rather than becoming falsely fresh or missing.
# ``missing`` means no artifact/timestamp exists.  ``degraded`` is reserved for
# a source that was present but could not be trusted (error, timeout, or peer
# failure).
FRESHNESS_THRESHOLDS: Dict[str, Dict[str, int]] = {
    "worker_heartbeat": {"fresh": 120, "aging": 300, "stale": 900},
    "resolver": {"fresh": 900, "aging": 1800, "stale": 3600},
    "live_feed": {"fresh": 300, "aging": 900, "stale": 3600},
    "market_data": {"fresh": 300, "aging": 900, "stale": 3600},
    "pick_audit": {"fresh": 86400, "aging": 172800, "stale": 604800},
    "combined_angles": {"fresh": 86400, "aging": 604800, "stale": 2592000},
    "pump_desk": {"fresh": 1200, "aging": 3600, "stale": 7200},
    "learning_health": {"fresh": 900, "aging": 3600, "stale": 14400},
    "learning_outcomes": {"fresh": 3600, "aging": 21600, "stale": 86400},
    "message_intel_live": {"fresh": 900, "aging": 3600, "stale": 7200},
    "message_intel_archive": {"fresh": 86400, "aging": 604800, "stale": 2592000},
    "github": {"fresh": 3600, "aging": 86400, "stale": 604800},
}

_FRESHNESS_ORDER = {"fresh": 0, "aging": 1, "stale": 2, "missing": 3, "degraded": 4}


# The surface is intentionally explicit even though this repository does not
# yet ship the review queue.  It gives future bots a stable hand-off contract.
APPROVAL_POLICY: Dict[str, Dict[str, str]] = {
    "infrastructure": {
        "approver_role": "platform_operator",
        "surface": "operator_review_queue",
        "examples": "restart, redeploy, scaling, configuration, or worker changes",
    },
    "security": {
        "approver_role": "security_operator",
        "surface": "security_review_queue",
        "examples": "rate limits, access changes, blocks, or credential policy",
    },
    "learning": {
        "approver_role": "learning_owner",
        "surface": "learning_review_queue",
        "examples": "weight changes, grading corrections, or learning-record writes",
    },
    "content": {
        "approver_role": "content_owner",
        "surface": "github_pull_request",
        "examples": "release notes, product copy, documentation, or publishing",
    },
}


def _parse_utc(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _thresholds_for(source: str) -> Dict[str, int]:
    return FRESHNESS_THRESHOLDS.get(source, {"fresh": 0, "aging": 0, "stale": 0})


def classify_freshness(
    source: str,
    captured_at: Any = None,
    *,
    now: Optional[datetime] = None,
    degraded: bool = False,
    mode: Optional[str] = None,
    authoritative: bool = True,
) -> Dict[str, Any]:
    """Return a serializable source-specific freshness envelope."""
    thresholds = _thresholds_for(source)
    parsed = _parse_utc(captured_at)
    status = "degraded" if degraded else "missing"
    age_seconds: Optional[float] = None
    if not degraded and parsed is not None:
        reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        age_seconds = max(0.0, (reference - parsed).total_seconds())
        if age_seconds <= thresholds["fresh"]:
            status = "fresh"
        elif age_seconds <= thresholds["aging"]:
            status = "aging"
        else:
            status = "stale"

    envelope: Dict[str, Any] = {
        "source": source,
        "status": status,
        "captured_at": str(captured_at) if captured_at else None,
        "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
        "authoritative": bool(authoritative),
        "thresholds_seconds": dict(thresholds),
    }
    if mode:
        envelope["mode"] = mode
        if mode == "archive":
            envelope["claim_scope"] = "historical"
        elif mode == "live":
            envelope["claim_scope"] = "current"
    return envelope


def aggregate_freshness(sources: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Summarize multiple source envelopes without hiding the worst state."""
    items = [dict(item) for item in sources]
    if not items:
        return {
            "status": "missing",
            "observed_at": None,
            "age_seconds": None,
            "sources": [],
        }
    worst = max(items, key=lambda item: _FRESHNESS_ORDER.get(str(item.get("status")), 4))
    observed = [item.get("captured_at") for item in items if item.get("captured_at")]
    ages = [item.get("age_seconds") for item in items if item.get("age_seconds") is not None]
    return {
        "status": worst.get("status", "missing"),
        "observed_at": max(observed) if observed else None,
        "age_seconds": max(ages) if ages else None,
        "sources": items,
    }


def approval_for(
    action_category: Optional[str] = None,
    *,
    state_changing: bool = False,
) -> Dict[str, Any]:
    """Describe the human gate for a proposed action."""
    category = str(action_category or "").strip().lower()
    rule = APPROVAL_POLICY.get(category)
    if state_changing and rule is None:
        # Unknown mutations fail closed rather than becoming an accidental
        # autonomous-action escape hatch.
        category = category or "unknown"
        rule = {
            "approver_role": "designated_owner",
            "surface": "operator_review_queue",
        }
    required = bool(state_changing)
    return {
        "required": required,
        "status": "pending" if required else "not_required",
        "action_category": category or None,
        "approver_role": rule["approver_role"] if required else None,
        "surface": rule["surface"] if required else None,
        "approval_id": None,
        "approved_at": None,
    }


def bot_contract(
    *,
    source: str = "unknown",
    captured_at: Any = None,
    freshness: Optional[Mapping[str, Any]] = None,
    sources: Optional[Iterable[Mapping[str, Any]]] = None,
    confidence: Optional[float] = None,
    action_category: Optional[str] = None,
    state_changing: bool = False,
    degraded: bool = False,
    mode: Optional[str] = None,
    authoritative: bool = True,
) -> Dict[str, Any]:
    """Build the common fields required on supervised bot responses."""
    if sources is not None:
        freshness_value = aggregate_freshness(sources)
    elif freshness is not None:
        freshness_value = dict(freshness)
    else:
        freshness_value = classify_freshness(
            source,
            captured_at,
            degraded=degraded,
            mode=mode,
            authoritative=authoritative,
        )
    normalized_confidence: Optional[float]
    try:
        normalized_confidence = (
            None if confidence is None else max(0.0, min(1.0, float(confidence)))
        )
    except (TypeError, ValueError):
        normalized_confidence = None
    approval = approval_for(action_category, state_changing=state_changing)
    return {
        "freshness": freshness_value,
        "confidence": normalized_confidence,
        "approval": approval,
        # Kept at the top level for simple consumers and backwards-compatible
        # with the blueprint's original approval_required field.
        "approval_required": approval["required"],
    }


def with_bot_contract(payload: Mapping[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """Add common contract fields without mutating the caller's payload."""
    result = dict(payload)
    result.update(bot_contract(**kwargs))
    return result
