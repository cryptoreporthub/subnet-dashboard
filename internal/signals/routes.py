"""Signal pipeline HTTP routes (Phase L slice 1)."""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Query

from internal.signals.pipeline import generate_signals
from internal.signals.store import SignalStore

signals_router = APIRouter(tags=["signals"])


@signals_router.get("/api/signals")
async def api_signals(
    subnet_id: Optional[int] = Query(None),
    since: Optional[str] = Query(None, description="ISO timestamp — return log entries since"),
    refresh: bool = Query(True, description="Regenerate live signals before responding"),
):
    if refresh:
        result = await asyncio.to_thread(generate_signals, True)
        signals = result.get("signals") or []
        meta = result.get("meta") or {}
    else:
        store = SignalStore()
        signals = store.query(subnet_id=subnet_id, since=since)
        meta = {"count": len(signals), "appended": 0, "cached": True}
    if refresh and subnet_id is not None:
        signals = [s for s in signals if s.get("subnet_id") == subnet_id]
    elif refresh and since:
        since_signals = SignalStore().query(since=since)
        if since_signals:
            meta["log_since"] = len(since_signals)
    return {"status": "success", "meta": meta, "signals": signals}


@signals_router.get("/api/signals/summary")
async def api_signals_summary(refresh: bool = Query(False)):
    if refresh:
        await asyncio.to_thread(generate_signals, True)
    return SignalStore().summary()
