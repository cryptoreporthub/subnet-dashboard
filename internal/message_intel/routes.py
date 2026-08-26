"""FastAPI routes for /api/message-intel/* (mounted via learning_router)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query, Request
from starlette.concurrency import run_in_threadpool

from internal.message_intel import engine
from internal.message_intel.entitlements import entitlement_from_request, entitlement_payload
from internal.message_intel.summary import summarize_message_intel

logger = logging.getLogger(__name__)

message_intel_router = APIRouter(tags=["message-intel"])


def _upgrade_response(feature: str, tier: str, route: str = "") -> Dict[str, Any]:
    return {
        "status": "upgrade_required",
        "feature": feature,
        "required_tier": tier,
        "route": route,
        "message": f"{feature} is available on {tier.upper()} or above.",
        "upgrade_prompt": {
            "title": f"Upgrade to {tier.upper()}",
            "body": f"Your current plan does not include {feature}.",
            "cta": "Beta access may still unlock this surface; no payment flow is implemented.",
        },
    }


def _message_contract(*, live: bool, captured_at: Optional[str], degraded: bool = False) -> Dict[str, Any]:
    from internal.ops.bot_policy import bot_contract

    return bot_contract(
        source="message_intel_live" if live else "message_intel_archive",
        captured_at=captured_at,
        degraded=degraded,
        mode="live" if live else "archive",
        authoritative=live,
    )


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
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    min_conviction: Optional[float] = Query(default=None, ge=0),
    netuid: Optional[int] = Query(default=None, ge=0),
    topic: Optional[str] = Query(default=None, min_length=1, max_length=32),
    author_id: Optional[str] = Query(default=None, min_length=1, max_length=128),
):
    """Primary message-intel list endpoint (honest-empty when no messages)."""
    ent = entitlement_from_request(request)
    try:
        # engine.list_messages() -> build_telegram_proof_band() runs a SQLite
        # query that can block on the DB's write lock while the Telegram
        # listener is ingesting — a live py-spy dump caught this exact route
        # (the most frequently polled endpoint in the app) holding the event
        # loop. Dispatch off-thread so /health can never queue behind it.
        payload = await run_in_threadpool(
            engine.list_messages,
            limit=limit,
            offset=offset,
            min_conviction=min_conviction,
            netuid=netuid,
            topic=topic,
            author_id=author_id,
        )
        payload["entitlement"] = entitlement_payload(ent)
        listener = (payload.get("meta") or {}).get("listener") or {}
        stats = payload.get("meta") or {}
        live = bool(listener.get("live"))
        payload.update(
            _message_contract(
                live=live,
                captured_at=stats.get("last_message_at"),
                degraded=not bool(stats.get("ok", True)),
            )
        )
        return payload
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
            **_message_contract(live=False, captured_at=None, degraded=True),
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
    contract = _message_contract(
        live=bool(listener.get("live")),
        captured_at=stats.get("last_message_at"),
        degraded=not bool(stats.get("ok", True)),
    )
    return {
        "status": "success",
        "listener": listener,
        "store": stats,
        "sources": source_status(),
        "outcomes": outcome_loop_status(),
        "live": bool(listener.get("live")),
        "empty": int(stats.get("total_messages") or 0) == 0,
        **contract,
    }


@message_intel_router.get("/api/message-intel/list")
async def api_message_intel_list(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    min_conviction: Optional[float] = Query(default=None, ge=0),
    netuid: Optional[int] = Query(default=None, ge=0),
    topic: Optional[str] = Query(default=None, min_length=1, max_length=32),
    author_id: Optional[str] = Query(default=None, min_length=1, max_length=128),
):
    try:
        return await run_in_threadpool(
            engine.list_messages,
            limit=limit,
            offset=offset,
            min_conviction=min_conviction,
            netuid=netuid,
            topic=topic,
            author_id=author_id,
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
    request: Request,
    days: int = Query(default=7, ge=1, le=30),
    limit: int = Query(default=8, ge=1, le=50),
):
    ent = entitlement_from_request(request)
    # build_weekly_authors() does synchronous JSON parsing over stored
    # messages — a live py-spy dump caught this route blocking the
    # MainThread/event loop directly (it was never dispatched off-thread).
    from internal.message_intel.rollup import build_author_reliability_rows, build_reaction_crowns

    authors, reaction_crowns = await run_in_threadpool(
        lambda: (
            build_author_reliability_rows(days=days, limit=limit),
            build_reaction_crowns(days=days),
        )
    )
    return {
        "status": "success",
        "days": days,
        "count": len(authors),
        "authors": authors,
        "reaction_crowns": reaction_crowns,
        "empty": len(authors) == 0,
        "entitlement": entitlement_payload(ent),
    }


@message_intel_router.get("/api/message-intel/trending-v2")
async def api_message_intel_trending_v2(
    request: Request,
    limit: int = Query(default=8, ge=1, le=50),
    rank_hours: int = Query(default=1, ge=1, le=24),
    window_hours: int = Query(default=24, ge=1, le=48),
):
    ent = entitlement_from_request(request)
    from internal.message_intel.rollup import build_trending_subnets

    try:
        result = await run_in_threadpool(
            build_trending_subnets,
            limit=limit,
            rank_hours=rank_hours,
            window_hours=window_hours,
            registry_names=engine._registry_subnet_names(),
        )
    except Exception as exc:
        logger.error("message-intel trending v2 failed: %s", exc)
        return {
            "status": "error",
            "count": 0,
            "items": [],
            "trending": [],
            "empty": True,
            "error": str(exc),
        }
    return {
        "status": "success",
        "count": len(result),
        "items": result,
        "trending": result,
        "window": f"{rank_hours}h/{window_hours}h",
        "empty": len(result) == 0,
        "entitlement": entitlement_payload(ent),
    }


@message_intel_router.get("/api/message-intel/callers")
async def api_message_intel_callers(
    request: Request,
    days: int = Query(default=30, ge=1, le=90),
    limit: int = Query(default=25, ge=1, le=50),
):
    """Resolved, qualifying Telegram-call accuracy only; never engagement."""
    from internal.message_intel.rollup import build_telegram_caller_leaderboard
    if days not in (1, 7, 30, 90):
        return {"status": "error", "error": "days must be one of 1, 7, 30, or 90", "callers": []}
    result = await run_in_threadpool(build_telegram_caller_leaderboard, days=days, limit=limit)
    return {"status": "success", **result}


@message_intel_router.get("/api/message-intel/callers/{author_id}/receipts")
async def api_message_intel_caller_receipts(
    request: Request,
    author_id: str,
    days: int = Query(default=30, ge=1, le=90),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
):
    """Public proof receipts for one stable Telegram author identity."""
    from internal.message_intel.rollup import list_telegram_caller_receipts
    if days not in (1, 7, 30, 90):
        return {"status": "error", "error": "days must be one of 1, 7, 30, or 90", "receipts": []}
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
    request: Request,
    limit: int = Query(default=12, ge=1, le=50),
):
    """Evidence-qualified current Telegram consensus, grouped by subnet."""
    return await run_in_threadpool(engine.list_subnet_telegram_conviction, limit=limit)


@message_intel_router.get("/api/message-intel/subnet-conviction/{netuid}")
async def api_subnet_telegram_conviction_detail(request: Request, netuid: int):
    """One subnet's consensus plus current calls and resolved proof receipts."""
    return await run_in_threadpool(engine.list_subnet_telegram_conviction, netuid=netuid, limit=1)


@message_intel_router.get("/api/message-intel/divergence")
async def api_telegram_divergence(
    request: Request,
    days: int = Query(default=7, ge=1, le=30),
    limit: int = Query(default=8, ge=1, le=50),
):
    """Telegram-only consensus/outcome stories; SQLite work stays off the event loop."""
    return await run_in_threadpool(engine.list_telegram_divergence_stories, days=days, limit=limit)


@message_intel_router.get("/api/message-intel/divergence/{netuid}")
async def api_telegram_divergence_detail(
    request: Request,
    netuid: int,
    days: int = Query(default=7, ge=1, le=30),
):
    """One subnet's auditable Telegram consensus/outcome story."""
    return await run_in_threadpool(
        engine.list_telegram_divergence_stories, netuid=netuid, days=days, limit=1
    )
