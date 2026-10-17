"""SimiVision API routes (slice 13 — chat; §17.F5 streaming)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from internal.rate_limit import limit_or_noop, strict_limit
from internal.simivision.chat_service import (
    handle_simivision_chat,
    iter_simivision_chat_chunks,
)

logger = logging.getLogger(__name__)

simivision_router = APIRouter(tags=["simivision"])

# The message is forwarded to a paid LLM call; output is capped at 400 tokens but input was not.
MAX_CHAT_MESSAGE_CHARS = 2000


def _wants_stream(payload: dict, request: Request) -> bool:
    if str(request.query_params.get("stream", "")).lower() in {"1", "true", "yes"}:
        return True
    flag = (payload or {}).get("stream")
    return flag is True or str(flag).lower() in {"1", "true", "yes"}


@simivision_router.post("/api/simivision/chat")
@limit_or_noop(strict_limit(), override_defaults=True)
async def api_simivision_chat(request: Request):
    """LLM chat for SimiVision. Default JSON; ``stream=true`` → SSE chunks."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    message = (payload or {}).get("message", "") or ""
    if not isinstance(message, str) or len(message) > MAX_CHAT_MESSAGE_CHARS:
        return JSONResponse(
            {"error": f"message must be a string of at most {MAX_CHAT_MESSAGE_CHARS} characters"},
            status_code=422,
        )
    if _wants_stream(payload or {}, request):
        return StreamingResponse(
            iter_simivision_chat_chunks(message),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    return await handle_simivision_chat(message)
