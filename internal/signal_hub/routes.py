"""Phase O — signal hub HTTP routes."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Query

from internal.signal_hub.tracker import hub_signals_list, hub_status

signal_hub_router = APIRouter(tags=["signal-hub"])


@signal_hub_router.get("/api/signal-hub/status")
async def api_signal_hub_status(
    refresh: bool = Query(False, description="Run one hub cycle before responding"),
) -> Dict[str, Any]:
    return hub_status(refresh=refresh)


@signal_hub_router.get("/api/signal-hub/signals")
async def api_signal_hub_signals(
    refresh: bool = Query(False, description="Run one hub cycle before responding"),
) -> Dict[str, Any]:
    if refresh:
        hub_status(refresh=True)
    return hub_signals_list()
