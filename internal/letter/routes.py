"""§17.F4 — weekly letter HTTP routes."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from internal.letter.brain_letter import build_brain_letter
from internal.letter.generator import build_daily_letter, build_weekly_letter

letter_router = APIRouter(tags=["letter"])
logger = logging.getLogger(__name__)

_BRAIN_TTL = float(os.environ.get("BRAIN_LETTER_CACHE_SECONDS", "60"))
_BRAIN_TIMEOUT = float(os.environ.get("BRAIN_LETTER_TIMEOUT_SECONDS", "8"))
LETTER_HANDLER_TIMEOUT = float(os.environ.get("LETTER_HANDLER_TIMEOUT_SECONDS", "8"))
_BRAIN_CACHE: Dict[str, Any] = {"at": 0.0, "payload": None}


async def _to_thread_timeout(fn, timeout_s: float, *, label: str):
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.warning("%s timed out after %.1fs", label, timeout_s)
        raise


def _quiet_brain() -> Dict[str, Any]:
    return {
        "status": "ok",
        "empty": True,
        "date": None,
        "pick": {},
        "outlook": "Brief refresh delayed — retry shortly.",
        "trust_banner": {},
        "brain_ui_ready": False,
        "watchdog": {},
        "working": {"ready": False, "top_price_signals": [], "disclaimer": ""},
        "markdown": "",
        "yesterday_outcome": None,
        "seed_strip": [],
        "desk_block": "",
        "source": "/api/letter/brain",
    }


@letter_router.get("/api/letter/weekly")
async def api_letter_weekly() -> Dict[str, Any]:
    try:
        return await _to_thread_timeout(build_weekly_letter, LETTER_HANDLER_TIMEOUT, label="letter-weekly")
    except asyncio.TimeoutError:
        return {
            "status": "timeout",
            "empty": True,
            "week_of": None,
            "top_pick": {"available": False, "summary": None},
            "win_rate": {"available": False, "win_pct": None, "total_closed": 0},
            "scenarios": [],
            "markdown": "",
        }


@letter_router.get("/api/letter/daily")
async def api_letter_daily(date: Optional[str] = Query(None)) -> Dict[str, Any]:
    def _build():
        return build_daily_letter(date=date)

    try:
        return await _to_thread_timeout(_build, LETTER_HANDLER_TIMEOUT, label="letter-daily")
    except asyncio.TimeoutError:
        return {
            "status": "timeout",
            "empty": True,
            "date": date,
            "default_window": "yesterday_utc",
            "picks": [],
            "resolutions": [],
            "scenarios": [],
            "alerts": [],
            "stats": {"pick_count": 0, "resolved_count": 0, "correct": 0, "wrong": 0},
            "markdown": "",
        }


@letter_router.get("/api/letter/brain")
async def api_letter_brain() -> Dict[str, Any]:
    """§21 L11 — today's living brain narrative (RF-2 trust_banner only).

    Never block the ASGI event loop — Fly single-worker wedges if this runs sync.
    """
    now = time.time()
    cached = _BRAIN_CACHE.get("payload")
    if isinstance(cached, dict) and now - float(_BRAIN_CACHE.get("at") or 0) < _BRAIN_TTL:
        return cached
    try:
        payload = await asyncio.wait_for(
            asyncio.to_thread(build_brain_letter),
            timeout=_BRAIN_TIMEOUT,
        )
        if isinstance(payload, dict):
            _BRAIN_CACHE["payload"] = payload
            _BRAIN_CACHE["at"] = now
            return payload
    except asyncio.TimeoutError:
        logger.warning("brain letter timed out after %.1fs", _BRAIN_TIMEOUT)
    except Exception as exc:
        logger.warning("brain letter failed: %s", exc)
    if isinstance(cached, dict):
        return cached
    return _quiet_brain()
