"""Append-only human approval store. No approval means no mutation.

Policy: bots may observe and propose, but cannot change system state without
a recorded human approval. Approvals expire on the clock and when required
evidence becomes stale or degraded.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from internal.ops.bot_policy import APPROVAL_POLICY, approval_for

STORE_ENV = "APPROVAL_STORE_PATH"
DEFAULT_STORE_PATH = "data/bot_approvals.json"

# Policy §1 expiry: critical is short-lived; everything else lasts a day.
EXPIRY_SECONDS = {
    "critical": 3600,
    "high": 86400,
    "medium": 86400,
    "low": 86400,
}

RISK_LEVELS = ("low", "medium", "high", "critical")
STATUSES = ("pending", "approved", "rejected", "expired")
_BOT_APPROVERS = frozenset(
    {
        "mission_control",
        "orchestrator",
        "sentinel",
        "drift_qa",
        "proof_scout",
        "market_desk",
        "shield",
        "concierge",
        "content_curator",
        "remedy",
    }
)

_LOCK = threading.Lock()


class ApprovalDenied(RuntimeError):
    """Raised when a mutation is attempted without a valid human approval."""


@dataclass
class ApprovalRecord:
    id: str
    action_type: str
    action_category: Optional[str]
    risk_level: str
    evidence_references: List[str]
    requested_by: str
    status: str
    requested_at: str
    expires_at: str
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    rejected_reason: Optional[str] = None
    execution_result: Optional[Dict[str, Any]] = None
    audit_history: List[Dict[str, Any]] = field(default_factory=list)
    proposal: Optional[Dict[str, Any]] = None
    freshness: Optional[Dict[str, Any]] = None
    run_id: Optional[str] = None
    approver_role: Optional[str] = None
    surface: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ApprovalRecord":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in payload.items() if k in known})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utcnow_z() -> str:
    return _utcnow().isoformat().replace("+00:00", "Z")


def _parse_utc(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def store_path() -> str:
    return os.environ.get(STORE_ENV, DEFAULT_STORE_PATH)


def _empty_store() -> Dict[str, Any]:
    return {"records": []}


def _load_store(path: str) -> Dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict) and isinstance(data.get("records"), list):
            return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return _empty_store()


def _save_store(path: str, data: Dict[str, Any]) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    os.replace(tmp, path)


def _log(event: str, record: ApprovalRecord) -> None:
    try:
        from internal.ops import notify as _notify

        logger = getattr(_notify, "log_event", None) or getattr(_notify, "emit", None)
        if callable(logger):
            logger(event, record.to_dict())
            return
    except Exception:
        pass
    import logging

    logging.getLogger(__name__).info("approval %s id=%s status=%s", event, record.id, record.status)


def _normalize_risk(risk_level: str) -> str:
    level = str(risk_level or "low").strip().lower()
    return level if level in RISK_LEVELS else "high"


def _freshness_blocks(freshness: Optional[Dict[str, Any]]) -> bool:
    if not freshness:
        return False
    status = str(freshness.get("status") or "").lower()
    return status in {"stale", "missing", "degraded"}


def _expired(record: ApprovalRecord, *, now: Optional[datetime] = None) -> bool:
    if record.status == "expired":
        return True
    if record.status == "rejected":
        return False
    clock = now or _utcnow()
    expires = _parse_utc(record.expires_at)
    if expires is not None and clock >= expires:
        return True
    return record.status == "approved" and _freshness_blocks(record.freshness)


def _mark_expired(record: ApprovalRecord) -> ApprovalRecord:
    if record.status == "expired":
        return record
    record.status = "expired"
    record.audit_history.append(
        {"event": "expired", "at": _utcnow_z()}
    )
    return record


def _put(record: ApprovalRecord) -> ApprovalRecord:
    path = store_path()
    with _LOCK:
        data = _load_store(path)
        records = data["records"]
        replaced = False
        for idx, item in enumerate(records):
            if item.get("id") == record.id:
                records[idx] = record.to_dict()
                replaced = True
                break
        if not replaced:
            records.append(record.to_dict())
        _save_store(path, data)
    return record


def get_record(record_id: str) -> Optional[ApprovalRecord]:
    path = store_path()
    with _LOCK:
        data = _load_store(path)
    for item in data["records"]:
        if item.get("id") == record_id:
            return ApprovalRecord.from_dict(item)
    return None


def find_by_run_id(run_id: Optional[str]) -> Optional[ApprovalRecord]:
    if not run_id:
        return None
    path = store_path()
    with _LOCK:
        data = _load_store(path)
    for item in reversed(data["records"]):
        if item.get("run_id") == run_id:
            return ApprovalRecord.from_dict(item)
    return None


def request_approval(
    action_type: str,
    risk_level: str,
    evidence_refs: Optional[List[str]] = None,
    requested_by: str = "mission_control",
    *,
    action_category: Optional[str] = None,
    proposal: Optional[Dict[str, Any]] = None,
    freshness: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
    state_changing: bool = True,
) -> ApprovalRecord:
    """Create a pending human-approval record. Never executes the action."""
    existing = find_by_run_id(run_id)
    if existing and existing.status in {"pending", "approved"} and not _expired(existing):
        return existing

    risk = _normalize_risk(risk_level)
    gate = approval_for(action_category, state_changing=state_changing)
    category = gate.get("action_category") or (action_category or "").strip().lower() or None
    if state_changing and category and category not in APPROVAL_POLICY and not gate.get("approver_role"):
        category = category or "unknown"
    now = _utcnow()
    ttl = EXPIRY_SECONDS.get(risk, EXPIRY_SECONDS["high"])
    record = ApprovalRecord(
        id=str(uuid.uuid4()),
        action_type=str(action_type or "unknown"),
        action_category=category,
        risk_level=risk,
        evidence_references=[str(item) for item in (evidence_refs or [])],
        requested_by=str(requested_by or "mission_control"),
        status="pending",
        requested_at=now.isoformat().replace("+00:00", "Z"),
        expires_at=(now + timedelta(seconds=ttl)).isoformat().replace("+00:00", "Z"),
        proposal=proposal,
        freshness=dict(freshness) if freshness else None,
        run_id=run_id,
        approver_role=gate.get("approver_role"),
        surface=gate.get("surface"),
        audit_history=[{"event": "requested", "at": _utcnow_z(), "by": requested_by}],
    )
    _put(record)
    _log("requested", record)
    return record


def approve(record_id: str, approver: str) -> ApprovalRecord:
    identity = str(approver or "").strip()
    if not identity:
        raise ApprovalDenied("approver identity is required")
    if identity.lower() in _BOT_APPROVERS:
        raise ApprovalDenied("approver must be a human with the named role, not a bot")
    record = get_record(record_id)
    if record is None:
        raise ApprovalDenied(f"approval record not found: {record_id}")
    if _expired(record):
        _put(_mark_expired(record))
        raise ApprovalDenied("approval has expired")
    if record.status == "rejected":
        raise ApprovalDenied("approval was rejected")
    if record.status == "approved":
        return record
    record.status = "approved"
    record.approved_by = identity
    record.approved_at = _utcnow_z()
    record.audit_history.append({"event": "approved", "at": record.approved_at, "by": identity})
    _put(record)
    _log("approved", record)
    return record


def reject(record_id: str, approver: str, reason: str = "") -> ApprovalRecord:
    identity = str(approver or "").strip()
    if not identity:
        raise ApprovalDenied("approver identity is required")
    if identity.lower() in _BOT_APPROVERS:
        raise ApprovalDenied("approver must be a human with the named role, not a bot")
    record = get_record(record_id)
    if record is None:
        raise ApprovalDenied(f"approval record not found: {record_id}")
    record.status = "rejected"
    record.rejected_reason = str(reason or "")
    record.audit_history.append(
        {"event": "rejected", "at": _utcnow_z(), "by": identity, "reason": record.rejected_reason}
    )
    _put(record)
    _log("rejected", record)
    return record


def is_approved(record_id: str) -> bool:
    record = get_record(record_id)
    if record is None:
        return False
    if _expired(record):
        if record.status != "expired":
            _put(_mark_expired(record))
        return False
    return record.status == "approved"


def enforce_approval(record_id: str) -> ApprovalRecord:
    """Gate a mutation. Raises if the approval is missing, pending, rejected, or expired."""
    record = get_record(record_id)
    if record is None:
        raise ApprovalDenied("no approval = no mutation")
    if _expired(record):
        _put(_mark_expired(record))
        raise ApprovalDenied("approval has expired")
    if record.status != "approved":
        raise ApprovalDenied(f"no approval = no mutation (status={record.status})")
    return record
