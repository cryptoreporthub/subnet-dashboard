"""Phase N — calibration API routes."""

from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from internal.calibration.pipeline import (
    get_calibration_status,
    run_calibration_pipeline,
    start_retrain_async,
)

calibration_router = APIRouter(tags=["calibration"])


def _check_admin(request: Request) -> None:
    token = os.environ.get("CALIBRATION_ADMIN_TOKEN")
    if not token:
        return
    header = request.headers.get("X-Calibration-Token") or request.headers.get(
        "Authorization", ""
    ).removeprefix("Bearer ").strip()
    if header != token:
        raise HTTPException(status_code=403, detail="calibration admin token required")


@calibration_router.get("/api/calibration/status")
async def api_calibration_status() -> Dict[str, Any]:
    return get_calibration_status()


@calibration_router.post("/api/calibration/retrain")
async def api_calibration_retrain(request: Request) -> Dict[str, Any]:
    _check_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    dry_run = bool(body.get("dry_run", False))
    force = bool(body.get("force", False))
    async_mode = bool(body.get("async", True))

    if async_mode and not dry_run:
        result = start_retrain_async(dry_run=False, force=force)
        if not result.get("started"):
            raise HTTPException(status_code=409, detail=result.get("reason", "in_progress"))
        return {"status": "started", **result}

    return run_calibration_pipeline(dry_run=dry_run, force=force)
