"""Signal pipeline HTTP routes (Phase L slices 1–4)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from internal.signals.alerts import AlertEngine
from internal.signals.pipeline import generate_signals
from internal.signals.store import SignalStore
from internal.signals.ws_hub import get_signal_hub

logger = logging.getLogger(__name__)

signals_router = APIRouter(tags=["signals"])

_store: Optional[SignalStore] = None
_alerts: Optional[AlertEngine] = None


def _get_store() -> SignalStore:
    global _store
    if _store is None:
        _store = SignalStore()
    return _store


def _get_alerts() -> AlertEngine:
    global _alerts
    if _alerts is None:
        _alerts = AlertEngine()
    return _alerts


class AlertCreateIn(BaseModel):
    alert_type: str = Field(description="Alert category, e.g. manual or signal_change")
    message: str = Field(description="Human-readable alert text")
    severity: str = Field(default="info", description="info | warning | critical")
    details: Dict[str, Any] = Field(default_factory=dict)
    subnet_id: Optional[int] = None
    dedupe_key: Optional[str] = None
    active: bool = True


class WebhookSubscribeIn(BaseModel):
    url: str = Field(description="HTTPS webhook URL for alert callbacks")


async def _refresh_and_broadcast() -> Dict[str, Any]:
    result = await asyncio.to_thread(generate_signals, True)
    engine = _get_alerts()
    system = await asyncio.to_thread(engine.check_system_alerts)
    signal_alerts = await asyncio.to_thread(
        engine.record_signal_changes, result.get("changed_signals") or []
    )
    hub = get_signal_hub()
    await hub.broadcast("signals", {"signals": result.get("signals", []), "meta": result.get("meta")})
    new_alerts = system + signal_alerts
    if new_alerts:
        await hub.broadcast("alerts", {"alerts": new_alerts})
    return result


@signals_router.get("/api/signals")
async def api_signals(
    subnet_id: Optional[int] = Query(None),
    since: Optional[str] = Query(None, description="ISO timestamp — return log entries since"),
    refresh: bool = Query(True, description="Regenerate live signals before responding"),
):
    if refresh:
        result = await _refresh_and_broadcast()
        signals = result.get("signals") or []
        meta = result.get("meta") or {}
    else:
        store = _get_store()
        signals = store.query(subnet_id=subnet_id, since=since)
        meta = {"count": len(signals), "appended": 0, "cached": True}
    if refresh and subnet_id is not None:
        signals = [s for s in signals if s.get("subnet_id") == subnet_id]
    elif refresh and since:
        since_signals = _get_store().query(since=since)
        if since_signals:
            meta["log_since"] = len(since_signals)
    return {"status": "success", "meta": meta, "signals": signals}


@signals_router.get("/api/signals/summary")
async def api_signals_summary(refresh: bool = Query(False)):
    if refresh:
        await _refresh_and_broadcast()
    return _get_store().summary()


@signals_router.get("/api/alerts")
async def api_alerts(
    limit: int = Query(50, ge=1, le=200),
    active_only: bool = Query(False),
    refresh_checks: bool = Query(True),
):
    engine = _get_alerts()
    if refresh_checks:
        await asyncio.to_thread(engine.check_system_alerts)
    return engine.recent_alerts(limit=limit, active_only=active_only)


@signals_router.post("/api/alerts")
async def api_alerts_create(body: AlertCreateIn):
    try:
        return _get_alerts().create_alert(body.model_dump())
    except ValueError as exc:
        return {"status": "error", "detail": str(exc)}


@signals_router.post("/api/alerts/subscribe")
async def api_alerts_subscribe(body: WebhookSubscribeIn):
    try:
        return _get_alerts().subscribe_webhook(body.url)
    except ValueError as exc:
        return {"status": "error", "detail": str(exc)}


@signals_router.websocket("/ws/signals")
async def ws_signals(websocket: WebSocket):
    hub = get_signal_hub()
    await hub.connect(websocket)
    try:
        store = _get_store()
        await websocket.send_json(
            {
                "type": "connected",
                "data": {
                    "signals": store.latest_all(),
                    "alerts": _get_alerts().recent_alerts(limit=20).get("alerts", []),
                },
            }
        )
        while True:
            msg = await websocket.receive_text()
            if msg.strip().lower() in ("refresh", "ping"):
                result = await _refresh_and_broadcast()
                await websocket.send_json(
                    {
                        "type": "signals",
                        "data": {"signals": result.get("signals", []), "meta": result.get("meta")},
                    }
                )
            else:
                await websocket.send_json({"type": "pong", "data": {}})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WebSocket error: %s", exc)
    finally:
        await hub.disconnect(websocket)
