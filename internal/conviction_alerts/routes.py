"""Conviction-threshold alert routes (Phase O1)."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from internal.conviction_alerts.evaluate import (
    get_last_run_status,
    run_conviction_evaluation,
)
from internal.signals.alerts import AlertEngine

conviction_alerts_router = APIRouter(tags=["conviction-alerts"])

_engine: AlertEngine | None = None


def _get_engine() -> AlertEngine:
    global _engine
    if _engine is None:
        _engine = AlertEngine()
    return _engine


@conviction_alerts_router.get("/api/conviction-alerts/status")
async def api_conviction_alerts_status() -> Dict[str, Any]:
    return {"status": "ok", **get_last_run_status()}


@conviction_alerts_router.post("/api/conviction-alerts/notify")
async def api_conviction_alerts_notify() -> Dict[str, Any]:
    return run_conviction_evaluation(_get_engine())
