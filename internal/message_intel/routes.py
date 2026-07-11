"""FastAPI routes for /api/message-intel/* (mounted via learning_router)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Query, Request

from internal.message_intel import engine
from internal.message_intel.summary import summarize_message_intel

logger = logging.getLogger(__name__)

message_intel_router = APIRouter(tags=["message-intel"])


@message_intel_router.post("/api/message-intel/ingest")
async def api_message_intel_ingest(request: Request):
    """Ingest one message or a batch (``messages`` array)."""
    try:
        payload = await request.json()
    except Exception as exc:
        return {"status": "error", "error": f"Invalid JSON body: {exc}"}

    try:
        if isinstance(payload, dict) and isinstance(payload.get("messages"), list):
            return engine.ingest_batch(payload["messages"])
        if isinstance(payload, list):
            return engine.ingest_batch(payload)
        return engine.ingest_message(payload if isinstance(payload, dict) else {})
    except engine.MessageIntelUnavailable as exc:
        return {"status": "error", "error": f"Message intelligence package unavailable: {exc}"}
    except Exception as exc:
        logger.error("message-intel ingest failed: %s", exc)
        return {"status": "error", "error": str(exc)}


@message_intel_router.get("/api/message-intel/list")
async def api_message_intel_list(limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)):
    try:
        return engine.list_messages(limit=limit, offset=offset)
    except Exception as exc:
        logger.error("message-intel list failed: %s", exc)
        return {"status": "error", "messages": [], "error": str(exc)}


@message_intel_router.get("/api/message-intel/detail/{msg_id}")
async def api_message_intel_detail(msg_id: int):
    try:
        return engine.get_message_detail(msg_id)
    except Exception as exc:
        logger.error("message-intel detail failed: %s", exc)
        return {"status": "error", "error": str(exc)}


@message_intel_router.get("/api/message-intel/chatter")
async def api_message_intel_chatter(
    min_conviction: float = Query(default=60.0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
):
    try:
        return engine.list_chatter(min_conviction=min_conviction, limit=limit)
    except Exception as exc:
        logger.error("message-intel chatter failed: %s", exc)
        return {"status": "error", "messages": [], "error": str(exc)}


@message_intel_router.get("/api/message-intel/patterns")
async def api_message_intel_patterns(limit: int = Query(default=20, ge=1, le=100)):
    try:
        return engine.list_patterns(limit=limit)
    except Exception as exc:
        logger.error("message-intel patterns failed: %s", exc)
        return {"status": "error", "patterns": [], "error": str(exc)}


@message_intel_router.get("/api/message-intel/summary")
async def api_message_intel_summary():
    """Panel summary endpoint (also folded into /api/mindmap/state)."""
    return {"status": "success", "summary": summarize_message_intel()}
