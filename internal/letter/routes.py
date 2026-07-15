"""§17.F4 — weekly letter HTTP routes."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

from internal.letter.generator import build_daily_letter, build_weekly_letter

letter_router = APIRouter(tags=["letter"])


@letter_router.get("/api/letter/weekly")
async def api_letter_weekly() -> Dict[str, Any]:
    return build_weekly_letter()


@letter_router.get("/api/letter/daily")
async def api_letter_daily(date: Optional[str] = Query(None)) -> Dict[str, Any]:
    return build_daily_letter(date=date)
