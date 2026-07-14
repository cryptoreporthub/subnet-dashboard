"""SimiVision API routes (slice 13 — chat)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from internal.rate_limit import limit_or_noop, strict_limit
from internal.simivision.chat_service import handle_simivision_chat

logger = logging.getLogger(__name__)

simivision_router = APIRouter(tags=["simivision"])


@simivision_router.post("/api/simivision/chat")
@limit_or_noop(strict_limit(), override_defaults=True)
async def api_simivision_chat(request: Request):
    """LLM chat for SimiVision (Chutes AI with local explainer fallback)."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    message = (payload or {}).get("message", "") or ""
    return await handle_simivision_chat(message)
