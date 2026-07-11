"""FastAPI routes for decision lineage (/api/trace/*)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Request

from internal.trace.engine import record_lineage
from internal.trace.store import get_record, list_records
from internal.trace.summary import summarize_trace

logger = logging.getLogger(__name__)

trace_router = APIRouter(tags=["trace"])


@trace_router.get("/api/trace/list")
async def api_trace_list(limit: int = Query(default=50, ge=1, le=500)):
    """List recent signal→decision lineage records."""
    try:
        records = list_records(limit=limit)
        return {
            "status": "success",
            "count": len(records),
            "records": records,
            "summary": summarize_trace(),
        }
    except Exception as exc:
        logger.warning("trace list failed: %s", exc)
        return {"status": "error", "count": 0, "records": [], "error": str(exc)}


@trace_router.get("/api/trace/summary")
async def api_trace_summary():
    """Plain-language summary of live lineage state."""
    try:
        return {"status": "success", "text": summarize_trace()}
    except Exception as exc:
        logger.warning("trace summary failed: %s", exc)
        return {"status": "error", "text": "", "error": str(exc)}


@trace_router.get("/api/trace/{trace_id}")
async def api_trace_detail(trace_id: str):
    """Return one lineage record by id."""
    try:
        record = get_record(trace_id)
        if record is None:
            return {"status": "not_found", "record": None}
        return {"status": "success", "record": record}
    except Exception as exc:
        logger.warning("trace detail failed: %s", exc)
        return {"status": "error", "record": None, "error": str(exc)}


@trace_router.post("/api/trace/record")
async def api_trace_record(request: Request):
    """Record a new signal→decision lineage chain."""
    try:
        payload = await request.json()
    except Exception as exc:
        return {"status": "error", "error": f"Invalid JSON body: {exc}"}

    decision_type = payload.get("decision_type")
    decision = payload.get("decision")
    signals = payload.get("signals")
    if not decision_type or not isinstance(decision, dict):
        return {"status": "error", "error": "Missing decision_type or decision object"}
    if not isinstance(signals, list) or not signals:
        return {"status": "error", "error": "Missing signals array"}

    try:
        record = record_lineage(
            decision_type=str(decision_type),
            decision=decision,
            signals=signals,
            subnet=payload.get("subnet"),
            netuid=payload.get("netuid"),
        )
        return {"status": "success", "record": record}
    except Exception as exc:
        logger.warning("trace record failed: %s", exc)
        return {"status": "error", "error": str(exc)}
