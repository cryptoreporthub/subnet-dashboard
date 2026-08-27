"""Logging-only audit surface for supervised SimiVision bots.

Does not mutate app state, send mail, or page operators. Specialist bots
share this one logger so routing, approvals, and health checks have a
single inspectable event stream.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Mapping, Optional

logger = logging.getLogger("internal.ops.notify")


def log_event(
    event: str,
    payload: Optional[Mapping[str, Any]] = None,
    **fields: Any,
) -> Dict[str, Any]:
    """Record a bot decision or routing event. Returns the serialized record."""
    record: Dict[str, Any] = {"event": str(event)}
    if payload:
        record.update(dict(payload))
    record.update(fields)
    logger.info("%s", json.dumps(record, default=str, sort_keys=True))
    return record


def emit(event: str, payload: Optional[Mapping[str, Any]] = None, **fields: Any) -> Dict[str, Any]:
    return log_event(event, payload, **fields)
