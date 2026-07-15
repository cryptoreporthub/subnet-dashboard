"""§17.F4 — weekly letter HTTP routes."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from internal.letter.generator import build_weekly_letter

letter_router = APIRouter(tags=["letter"])


@letter_router.get("/api/letter/weekly")
async def api_letter_weekly() -> Dict[str, Any]:
    return build_weekly_letter()
