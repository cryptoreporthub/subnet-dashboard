"""Jinja context for message-intel (Phase M)."""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def build_message_intel_context(*, limit: int = 20) -> Dict[str, Any]:
    """Return message_intel panel data for GET /."""
    try:
        from internal.message_intel.engine import list_messages
        from internal.message_intel.summary import summarize_message_intel

        listed = list_messages(limit=limit, offset=0)
        return {
            "message_intel": {
                "messages": listed.get("messages") or [],
                "meta": listed.get("meta") or {},
                "sources": listed.get("sources") or {},
                "summary": summarize_message_intel(),
            }
        }
    except Exception as exc:
        logger.warning("message_intel context unavailable: %s", exc)
        return {
            "message_intel": {
                "messages": [],
                "meta": {"total_messages": 0, "ok": False},
                "sources": {},
                "summary": {
                    "text": "Message-intel warming up — social ingest unavailable on this deploy.",
                    "sentences": [],
                },
            }
        }
