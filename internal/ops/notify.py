"""Logging-only audit surface for supervised SimiVision bots.

Does not mutate app state, send mail, or page operators. Specialist bots
share this one logger so routing, approvals, and health checks have a
single inspectable event stream.

Policy §4 (evidence hygiene, applied here to the audit trail):
- Never log secrets, tokens, or raw Authorization / cookie headers.
- Redact known secret-bearing keys and Bearer values before emit.
- Return an audit_id (Shield path) or a serializable record (Drift/QA path).
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Mapping, Optional, Union

logger = logging.getLogger("internal.ops.notify")

_SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "x-auth-token",
        "x-write-api-token",
        "write_api_token",
        "write-api-token",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "client_secret",
        "private_key",
        "secret",
        "password",
        "passwd",
        "api_key",
        "apikey",
        "bearer",
    }
)

_SENSITIVE_KEY_SUFFIXES = (
    "_token",
    "_secret",
    "_password",
    "_passwd",
    "_api_key",
    "_apikey",
    "_private_key",
)

_BEARER_RE = re.compile(r"((?:Bearer|Basic|Token)\s+)\S+", re.IGNORECASE)
_AUTH_HEADER_RE = re.compile(r"(Authorization:\s*).+", re.IGNORECASE)
_QUERY_SECRET_RE = re.compile(
    r"((?:access_token|refresh_token|token|secret|password|api[_-]?key)=)([^&\s]+)",
    re.IGNORECASE,
)

_REDACTED = "[redacted]"
_MAX_RECENT = 500
_RECENT: Deque[Dict[str, Any]] = deque(maxlen=_MAX_RECENT)

# Shield uses the audit-id path; sibling bots keep the legacy record dict.
_SHIELD_BOT = "shield"


def _key_is_sensitive(key: str) -> bool:
    lowered = str(key).lower().replace("-", "_")
    if lowered in _SENSITIVE_KEYS:
        return True
    return lowered.endswith(_SENSITIVE_KEY_SUFFIXES)


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _redact_text(value: str) -> str:
    scrubbed = _BEARER_RE.sub(r"\1" + _REDACTED, value)
    scrubbed = _AUTH_HEADER_RE.sub(r"\1" + _REDACTED, scrubbed)
    scrubbed = _QUERY_SECRET_RE.sub(r"\1" + _REDACTED, scrubbed)
    return scrubbed


def redact(value: Any) -> Any:
    """Return a copy with secrets stripped. Never mutates the caller's object."""
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, Mapping):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            if _key_is_sensitive(str(key)):
                out[str(key)] = _REDACTED
            else:
                out[str(key)] = redact(item)
        return out
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value


def recent_records(limit: int = 50) -> List[Dict[str, Any]]:
    """In-memory window of recent audit records (tests / operator inspect)."""
    if limit <= 0:
        return []
    items = list(_RECENT)
    return items[-limit:]


def reset_records() -> None:
    """Clear the in-memory window. Logging-only; no app-state mutation."""
    _RECENT.clear()


def log_event(
    event: str,
    payload: Optional[Mapping[str, Any]] = None,
    **fields: Any,
) -> Dict[str, Any]:
    """Record a bot decision or routing event. Returns the serialized record."""
    record: Dict[str, Any] = {"event": str(event)}
    if payload:
        record.update(redact(dict(payload)))
    record.update(redact(fields))
    logger.info("%s", json.dumps(record, default=str, sort_keys=True))
    return record


def emit(event: str, payload: Optional[Mapping[str, Any]] = None, **fields: Any) -> Dict[str, Any]:
    return log_event(event, payload, **fields)


def _legacy_notify(event: str, **fields: Any) -> Dict[str, Any]:
    """Drift/QA alias: nested ``payload=`` stays nested; returns the record dict."""
    record: Dict[str, Any] = {"event": str(event or "unknown").strip() or "unknown"}
    record.update(redact({key: value for key, value in fields.items() if value is not None}))
    logger.info("%s", json.dumps(record, default=str, sort_keys=True))
    return record


def log_status(message: str = "", *, level: str = "info", **fields: Any) -> Dict[str, Any]:
    """Emit a health/status log (``event=status``)."""
    return log_event("status", message=message, level=level, **fields)

def _audit_notify(
    event: str,
    *,
    bot: str,
    payload: Optional[Mapping[str, Any]] = None,
    run_id: Optional[str] = None,
    level: str = "info",
) -> str:
    """Shield audit path: redacted in-memory record; returns ``audit_id``."""
    audit_id = uuid.uuid4().hex[:16]
    record = {
        "audit_id": audit_id,
        "event": str(event),
        "bot": str(bot),
        "run_id": run_id,
        "recorded_at": _utcnow_z(),
        "payload": redact(payload or {}),
    }
    _RECENT.append(record)
    message = (
        "bot=%s event=%s run_id=%s audit_id=%s payload=%s"
        % (record["bot"], record["event"], record["run_id"], audit_id, record["payload"])
    )
    log_fn = getattr(logger, str(level).lower(), logger.info)
    if not callable(log_fn):
        log_fn = logger.info
    log_fn(message)
    return audit_id


def notify(event: str, **fields: Any) -> Union[str, Dict[str, Any]]:
    """Shared logging-only notify.

    Shield (audit_id str): ``notify(event, bot="shield", run_id=..., payload=...)``.

    Drift/QA / Mission Control (record dict): any other ``bot=`` keeps the legacy
    nested-payload record shape.
    """
    if str(fields.get("bot") or "").strip().lower() == _SHIELD_BOT:
        return _audit_notify(
            event,
            bot=str(fields["bot"]),
            payload=fields.get("payload"),
            run_id=fields.get("run_id"),
            level=str(fields.get("level") or "info"),
        )
    return _legacy_notify(event, **fields)
