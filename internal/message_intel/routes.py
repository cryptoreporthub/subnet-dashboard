"""FastAPI routes for /api/message-intel/* (mounted via learning_router)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Request
from starlette.concurrency import run_in_threadpool

from internal.message_intel import engine
from internal.message_intel.summary import summarize_message_intel

logger = logging.getLogger(__name__)

message_intel_router = APIRouter(tags=["message-intel"])


@message_intel_router.post("/api/message-intel/ingest")
async def api_message_intel_ingest(request: Request):
    """Ingest one message or a batch (``messages`` array)."""
    try:
        payload = await request.json()
    except Exception as exc:
        return {"status": "error", "error": f"Invalid JSON body: {exc}"}

    try:
        if isinstance(payload, dict) and isinstance(payload.get("messages"), list):
            return engine.ingest_batch(payload["messages"])
        if isinstance(payload, list):
            return engine.ingest_batch(payload)
        return engine.ingest_message(payload if isinstance(payload, dict) else {})
    except engine.MessageIntelUnavailable as exc:
        from internal.api_errors import public_error

        return public_error(exc, code="message_intel_unavailable", log="message-intel ingest unavailable")
    except Exception as exc:
        logger.error("message-intel ingest failed: %s", exc)
        from internal.api_errors import public_error

        return public_error(exc, code="ingest_failed", log="message-intel ingest failed")


@message_intel_router.get("/api/message-intel")
async def api_message_intel(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    min_conviction: Optional[float] = Query(default=None, ge=0),
    netuid: Optional[int] = Query(default=None, ge=0),
    topic: Optional[str] = Query(default=None, min_length=1, max_length=32),
):
    """Primary message-intel list endpoint (honest-empty when no messages)."""
    try:
        # engine.list_messages() -> build_telegram_proof_band() runs a SQLite
        # query that can block on the DB's write lock while the Telegram
        # listener is ingesting — a live py-spy dump caught this exact route
        # (the most frequently polled endpoint in the app) holding the event
        # loop. Dispatch off-thread so /health can never queue behind it.
        return await run_in_threadpool(
            engine.list_messages,
            limit=limit,
            offset=offset,
            min_conviction=min_conviction,
            netuid=netuid,
            topic=topic,
        )
    except Exception as exc:
        logger.error("message-intel list failed: %s", exc)
        from internal.message_intel.listener_service import listener_status

        return {
            "status": "success",
            "count": 0,
            "messages": [],
            "empty": True,
            "meta": {"total_messages": 0, "ok": False, "error": str(exc), "listener": listener_status()},
            "sources": {},
        }


@message_intel_router.get("/api/message-intel/status")
async def api_message_intel_status():
    """Listener + store health (no secrets). Honest when creds absent."""
    from internal.message_intel.listener_service import listener_status
    from internal.message_intel.outcome_loop import outcome_loop_status
    from internal.message_intel.store import live_stats
    from internal.message_intel.sources import source_status

    try:
        stats = live_stats()
    except Exception as exc:
        stats = {"ok": False, "error": str(exc), "total_messages": 0}
    listener = listener_status()
    return {
        "status": "success",
        "listener": listener,
        "store": stats,
        "sources": source_status(),
        "outcomes": outcome_loop_status(),
        "live": bool(listener.get("live")),
        "empty": int(stats.get("total_messages") or 0) == 0,
    }


@message_intel_router.get("/api/message-intel/list")
async def api_message_intel_list(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    min_conviction: Optional[float] = Query(default=None, ge=0),
    netuid: Optional[int] = Query(default=None, ge=0),
    topic: Optional[str] = Query(default=None, min_length=1, max_length=32),
):
    try:
        return await run_in_threadpool(
            engine.list_messages,
            limit=limit,
            offset=offset,
            min_conviction=min_conviction,
            netuid=netuid,
            topic=topic,
        )
    except Exception as exc:
        logger.error("message-intel list failed: %s", exc)
        return {"status": "error", "messages": [], "error": str(exc)}


@message_intel_router.get("/api/message-intel/detail/{msg_id}")
async def api_message_intel_detail(msg_id: int):
    try:
        return await run_in_threadpool(engine.get_message_detail, msg_id)
    except Exception as exc:
        logger.error("message-intel detail failed: %s", exc)
        from internal.api_errors import public_error

        return public_error(exc, code="detail_failed", log="message-intel detail failed")


@message_intel_router.get("/api/message-intel/chatter")
async def api_message_intel_chatter(
    min_conviction: float = Query(default=60.0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
):
    try:
        # Same SQLite/registry read path as list_messages() above — must not
        # run on the event loop (a live py-spy dump caught the MainThread
        # itself blocked here, not just a thread-pool worker).
        return await run_in_threadpool(engine.list_chatter, min_conviction=min_conviction, limit=limit)
    except Exception as exc:
        logger.error("message-intel chatter failed: %s", exc)
        return {"status": "error", "messages": [], "error": str(exc)}


@message_intel_router.get("/api/message-intel/authors")
async def api_message_intel_authors(
    days: int = Query(default=7, ge=1, le=30),
    limit: int = Query(default=8, ge=1, le=50),
):
    # build_weekly_authors() does synchronous JSON parsing over stored
    # messages — a live py-spy dump caught this route blocking the
    # MainThread/event loop directly (it was never dispatched off-thread).
    return await run_in_threadpool(engine.list_authors, days=days, limit=limit)


@message_intel_router.get("/api/message-intel/callers")
async def api_message_intel_callers(
    days: int = Query(default=30, ge=7, le=90),
    limit: int = Query(default=25, ge=1, le=50),
):
    """Resolved, qualifying Telegram-call accuracy only; never engagement."""
    from internal.message_intel.rollup import build_telegram_caller_leaderboard
    if days not in (7, 30, 90):
        return {"status": "error", "error": "days must be one of 7, 30, or 90", "callers": []}
    result = await run_in_threadpool(build_telegram_caller_leaderboard, days=days, limit=limit)
    return {"status": "success", **result}


@message_intel_router.get("/api/message-intel/callers/{author_id}/receipts")
async def api_message_intel_caller_receipts(
    author_id: str,
    days: int = Query(default=30, ge=7, le=90),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
):
    """Public proof receipts for one stable Telegram author identity."""
    from internal.message_intel.rollup import list_telegram_caller_receipts
    if days not in (7, 30, 90):
        return {"status": "error", "error": "days must be one of 7, 30, or 90", "receipts": []}
    result = await run_in_threadpool(
        list_telegram_caller_receipts, author_id=author_id, days=days, limit=limit, offset=offset
    )
    return {"status": "success", **result}


@message_intel_router.get("/api/message-intel/topics")
async def api_message_intel_topics(limit: int = Query(default=12, ge=1, le=50)):
    return await run_in_threadpool(engine.list_topics, limit=limit)


@message_intel_router.get("/api/message-intel/patterns")
async def api_message_intel_patterns(limit: int = Query(default=20, ge=1, le=100)):
    try:
        return await run_in_threadpool(engine.list_patterns, limit=limit)
    except Exception as exc:
        logger.error("message-intel patterns failed: %s", exc)
        return {"status": "error", "patterns": [], "error": str(exc)}


@message_intel_router.get("/api/message-intel/calibration")
async def api_message_intel_calibration():
    """Operator-visible health for outcome-backed Telegram calibration."""
    try:
        return {"status": "success", **await run_in_threadpool(engine.telegram_calibration_status)}
    except Exception as exc:
        logger.error("message-intel calibration status failed: %s", exc)
        return {"status": "error", "active": False, "error": str(exc)}


@message_intel_router.get("/api/message-intel/summary")
async def api_message_intel_summary():
    """Panel summary endpoint (also folded into /api/mindmap/state)."""
    summary = await run_in_threadpool(summarize_message_intel)
    return {"status": "success", "summary": summary}


@message_intel_router.get("/api/message-intel/social")
async def api_message_intel_social(limit: int = Query(default=6, ge=1, le=24)):
    """Per-subnet sentiment rollup from message_intel store (honest-empty)."""
    from internal.message_intel.context import build_social_sentiment_rows

    subnets: List[Dict[str, Any]] = []
    try:
        from server import _get_subnets_with_source

        subnets, _ = _get_subnets_with_source()
    except Exception:
        pass
    rows = await run_in_threadpool(build_social_sentiment_rows, subnets, limit=limit)
    return {"status": "success", "rows": rows, "empty": len(rows) == 0}


@message_intel_router.get("/api/message-intel/subnet-conviction")
async def api_subnet_telegram_conviction(
    limit: int = Query(default=12, ge=1, le=50),
):
    """Evidence-qualified current Telegram consensus, grouped by subnet."""
    return await run_in_threadpool(engine.list_subnet_telegram_conviction, limit=limit)


@message_intel_router.get("/api/message-intel/subnet-conviction/{netuid}")
async def api_subnet_telegram_conviction_detail(netuid: int):
    """One subnet's consensus plus current calls and resolved proof receipts."""
    return await run_in_threadpool(engine.list_subnet_telegram_conviction, netuid=netuid, limit=1)


@message_intel_router.get("/api/message-intel/divergence")
async def api_telegram_divergence(
    days: int = Query(default=7, ge=1, le=30),
    limit: int = Query(default=8, ge=1, le=50),
):
    """Telegram-only consensus/outcome stories; SQLite work stays off the event loop."""
    return await run_in_threadpool(engine.list_telegram_divergence_stories, days=days, limit=limit)


@message_intel_router.get("/api/message-intel/divergence/{netuid}")
async def api_telegram_divergence_detail(
    netuid: int,
    days: int = Query(default=7, ge=1, le=30),
):
    """One subnet's auditable Telegram consensus/outcome story."""
    return await run_in_threadpool(
        engine.list_telegram_divergence_stories, netuid=netuid, days=days, limit=1
    )
