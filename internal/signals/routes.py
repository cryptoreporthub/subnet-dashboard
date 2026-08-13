"""Signal pipeline HTTP routes (Phase L slices 1–4)."""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, model_validator

from internal.signals.alerts import AlertEngine
from internal.signals.pipeline import generate_signals
from internal.signals.store import SignalStore
from internal.signals.ws_hub import get_signal_hub

logger = logging.getLogger(__name__)

signals_router = APIRouter(tags=["signals"])

SIGNALS_HANDLER_TIMEOUT = float(os.environ.get("SIGNALS_HANDLER_TIMEOUT_SECONDS", "8"))
SIGNALS_FRESHNESS_SECONDS = int(
    os.environ.get("SIGNALS_FRESHNESS_SECONDS", "900")
)
_refresh_lock = threading.Lock()


async def _to_thread_timeout(fn, timeout_s: float, *, label: str):
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn), timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.warning("%s timed out after %.1fs", label, timeout_s)
        raise

try:
    from internal.signal_hub.routes import signal_hub_router

    signals_router.include_router(signal_hub_router)
except ImportError as _hub_exc:
    logger.warning("Signal hub routes unavailable: %s", _hub_exc)

try:
    from internal.conviction_alerts.routes import conviction_alerts_router

    signals_router.include_router(conviction_alerts_router)
except ImportError as _conviction_exc:
    logger.warning("Conviction alert routes unavailable: %s", _conviction_exc)

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
    subnet_id: Optional[int] = Field(default=None, description="Subnet netuid")
    netuid: Optional[int] = Field(default=None, description="Alias for subnet_id")
    dedupe_key: Optional[str] = None
    active: bool = True
    threshold_type: Optional[str] = Field(
        default=None, description="Metric for threshold alerts, e.g. price_change_24h"
    )
    threshold_value: Optional[float] = None
    threshold_operator: Optional[str] = Field(
        default="gte", description="gt | lt | gte | lte | eq"
    )

    @model_validator(mode="after")
    def _merge_netuid(self) -> "AlertCreateIn":
        if self.netuid is not None and self.subnet_id is None:
            self.subnet_id = self.netuid
        return self


class WebhookSubscribeIn(BaseModel):
    url: str = Field(description="HTTPS webhook URL for alert callbacks")


def _store_is_fresh(store: SignalStore) -> bool:
    refreshed_at = store.load().get("refreshed_at")
    if not refreshed_at:
        return False
    try:
        refreshed = datetime.fromisoformat(
            str(refreshed_at).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return False
    age = (datetime.now(timezone.utc) - refreshed).total_seconds()
    return age <= SIGNALS_FRESHNESS_SECONDS


async def _refresh_and_broadcast(
    *,
    only_if_stale: bool = False,
    fallback_signals: Optional[list[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    def _build():
        # The lock spans the freshness check and generation. A request that
        # waited for another refresh re-checks the store and returns its
        # result instead of launching a duplicate generator.
        with _refresh_lock:
            if only_if_stale:
                store = _get_store()
                cached = store.latest_all()
                if _store_is_fresh(store):
                    return (
                        {
                            "signals": cached,
                            "meta": {
                                "count": len(cached),
                                "appended": 0,
                                "cached": True,
                                "source": "fresh-cache",
                            },
                            "changed_signals": [],
                        },
                        [],
                        [],
                        [],
                    )

            result = generate_signals(True)
            engine = _get_alerts()
            system = engine.check_system_alerts()
            signal_alerts = engine.record_signal_changes(
                result.get("changed_signals") or []
            )
            composites = engine.evaluate_correlation_alerts(
                result.get("signals") or []
            )
            return result, system, signal_alerts, composites

    try:
        result, system, signal_alerts, composites = await _to_thread_timeout(
            _build, SIGNALS_HANDLER_TIMEOUT, label="signals-refresh"
        )
    except asyncio.TimeoutError:
        cached = list(fallback_signals or [])
        return {
            "signals": cached,
            "meta": {
                "count": len(cached),
                "appended": 0,
                "cached": bool(cached),
                "stale": True,
                "source": "timeout",
            },
            "changed_signals": [],
        }

    hub = get_signal_hub()
    await hub.broadcast("signals", {"signals": result.get("signals", []), "meta": result.get("meta")})
    new_alerts = system + signal_alerts + composites
    if new_alerts:
        await hub.broadcast("alerts", {"alerts": new_alerts})
    return result


@signals_router.get("/api/signals")
async def api_signals(
    subnet_id: Optional[int] = Query(None),
    since: Optional[str] = Query(None, description="ISO timestamp — return log entries since"),
    refresh: bool = Query(False, description="Regenerate live signals before responding"),
):
    if refresh:
        result = await _refresh_and_broadcast()
        signals = result.get("signals") or []
        meta = result.get("meta") or {}
    else:
        store = _get_store()
        signals = store.query(subnet_id=subnet_id, since=since)
        meta = {"count": len(signals), "appended": 0, "cached": True}
        if subnet_id is None and since is None and not _store_is_fresh(store):
            try:
                result = await _refresh_and_broadcast(
                    only_if_stale=True,
                    fallback_signals=signals,
                )
                signals = result.get("signals") or []
                meta = result.get("meta") or {}
            except Exception as exc:
                # Keep the endpoint useful during a transient feed failure.
                # The caller still gets the stale cache (if any), with an
                # explicit freshness failure instead of an HTTP 500.
                logger.warning("automatic signals refresh failed: %s", exc)
                meta.update(
                    {
                        "cached": True,
                        "stale": True,
                        "refresh_error": type(exc).__name__,
                    }
                )
    try:
        from internal.subnet_names import refresh_stored_names

        signals = refresh_stored_names(signals)
    except Exception:
        pass
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
    netuid: Optional[int] = Query(None, description="Filter by subnet netuid"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    status: Optional[Literal["active", "inactive"]] = Query(
        None, description="Filter by alert status"
    ),
):
    engine = _get_alerts()
    if refresh_checks:
        try:
            await _to_thread_timeout(engine.check_system_alerts, SIGNALS_HANDLER_TIMEOUT, label="alerts-system")
            signals = _get_store().latest_all()
            await _to_thread_timeout(
                lambda: engine.evaluate_correlation_alerts(signals),
                SIGNALS_HANDLER_TIMEOUT,
                label="alerts-correlation",
            )
        except asyncio.TimeoutError:
            pass
    return engine.recent_alerts(
        limit=limit,
        active_only=active_only,
        netuid=netuid,
        severity=severity,
        status=status,
    )


@signals_router.post("/api/alerts", status_code=201)
async def api_alerts_create(body: AlertCreateIn, response: Response):
    try:
        result = _get_alerts().create_alert(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("deduped"):
        response.status_code = 200
    return result


@signals_router.post("/api/alerts/subscribe")
async def api_alerts_subscribe(body: WebhookSubscribeIn):
    try:
        return _get_alerts().subscribe_webhook(body.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
            cmd = msg.strip().lower()
            if cmd == "ping":
                await websocket.send_json({"type": "pong", "data": {}})
            elif cmd == "refresh":
                await _refresh_and_broadcast()
            else:
                await websocket.send_json({"type": "pong", "data": {}})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WebSocket error: %s", exc)
    finally:
        await hub.disconnect(websocket)
