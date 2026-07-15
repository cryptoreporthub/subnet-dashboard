"""§17.F1 — watchlist HTTP routes."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter
from pydantic import BaseModel, Field

from internal.watchlist.store import load_watchlist, save_watchlist

watchlist_router = APIRouter(tags=["watchlist"])


class WatchlistPut(BaseModel):
    netuids: List[Any] = Field(default_factory=list)


@watchlist_router.get("/api/watchlist")
async def api_watchlist_get() -> Dict[str, Any]:
    data = load_watchlist()
    return {"status": "ok", "netuids": data.get("netuids") or [], "updated_at": data.get("updated_at")}


@watchlist_router.put("/api/watchlist")
async def api_watchlist_put(body: WatchlistPut) -> Dict[str, Any]:
    saved = save_watchlist(list(body.netuids))
    return {"status": "ok", "netuids": saved["netuids"], "updated_at": saved["updated_at"]}
