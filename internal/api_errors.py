"""Sanitized API error payloads (audit phase 3)."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def public_error(
    exc: BaseException,
    *,
    code: str = "request_failed",
    log: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a client-safe error dict; log the real exception server-side."""
    logger.warning("%s: %s", log or code, exc)
    return {"status": "error", "error": code}
