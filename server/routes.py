"""All API and web routes."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from server.config import *  # noqa: F403

import logging
import json

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/health")
def health_check():
    return PlainTextResponse("OK")

@router.get("/api/health")
def api_health_check():
    """JSON health probe for Fly.io / monitoring tooling."""
    return {"status": "ok"}

@router.get("/api/freshness")
def api_freshness():
    """Per-section 'last updated' timestamps for the dashboard freshness badges."""
    return _freshness_snapshot()

@router.get("/api/pick-history")
def api_pick_history():
    """Pick-of-the-Hour history + aggregate success metric."""
    return _hour_pick_history(limit=20)

from datastore.learning_engine import LearningEngine

@router.get("/api/weights")
def api_weights():
    """Get current expert weights."""
    engine = LearningEngine()
    return engine.get_stats()

@router.post("/api/feedback")
async def api_feedback(request: Request):
    """Record feedback for learning loop."""
    try:
        data = await request.json()
    except Exception:
        body = await request.body()
        if isinstance(body, bytes):
            data = json.loads(body)
        else:
            data = body or {}
    
    engine = LearningEngine()
    return engine.record_feedback(
        subnet_id=data.get("subnet_id"),
        recommendation=data.get("recommendation"),
        actual_performance=data.get("actual_performance", {})
    )