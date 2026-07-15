"""Message-intel ingest engine — normalize, persist, Soul-Map, trail."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from internal.message_intel.soul_sync import apply_batch_to_soul_map
from internal.message_intel.sources import source_status
from internal.message_intel.store import get_db, live_stats

logger = logging.getLogger(__name__)


class MessageIntelUnavailable(Exception):
    """Raised when core message_intel package cannot be loaded."""


def _load_pipeline():
    try:
        from message_intel.nlp_engine import NLPAnalyzer
        from message_intel.price_tracker import PriceTracker
    except ImportError as exc:
        raise MessageIntelUnavailable(str(exc)) from exc
    return NLPAnalyzer(), PriceTracker


def ingest_message(payload: Dict[str, Any], *, snapshot_price: bool = True) -> Dict[str, Any]:
    """Run NLP → jury → persist → optional price snapshot → Soul-Map/trail."""
    if not isinstance(payload, dict) or not payload.get("content"):
        return {"status": "error", "error": "Missing required field: content"}

    nlp, price_tracker = _load_pipeline()
    db = get_db()

    message_id, deduped = db.save_message(payload)
    if deduped:
        return {
            "status": "success",
            "message_id": message_id,
            "deduped": True,
            "sources": source_status(),
        }

    content = str(payload.get("content") or "")
    analysis = nlp.analyze(content)
    db.save_analysis(message_id, analysis)
    from internal.message_intel.jury import evaluate_message

    verdict = evaluate_message(message_id, content, analysis)
    db.save_verdict(message_id, verdict)

    price_result: Optional[Dict[str, Any]] = None
    if snapshot_price:
        try:
            price_tracker.db = db
            snap = price_tracker.snapshot(message_id)
            if snap is not None:
                price_result = {"tao_usd_price": snap}
            from internal.message_intel.soul_sync import _extract_netuids

            for netuid in _extract_netuids(analysis)[:1]:
                subnet_snap = price_tracker.snapshot_subnet(message_id, netuid)
                if subnet_snap is not None and price_result is not None:
                    price_result["subnet_netuid"] = netuid
                    price_result["subnet_price"] = subnet_snap
        except Exception as exc:
            logger.warning("Price snapshot skipped for message %s: %s", message_id, exc)
            price_result = {"error": str(exc)}

    soul = apply_batch_to_soul_map(
        batch_size=1,
        records=[
            {
                "message_id": message_id,
                "payload": payload,
                "analysis": analysis,
                "verdict": verdict,
            }
        ],
    )

    from internal.message_intel.signals_bridge import emit_social_alert_if_needed

    social_alert = emit_social_alert_if_needed(message_id, payload, verdict, analysis)

    return {
        "status": "success",
        "message_id": message_id,
        "deduped": False,
        "analysis": analysis,
        "verdict": verdict,
        "price_snapshot": price_result,
        "soul_map": soul,
        "social_alert": social_alert,
    }


def ingest_batch(messages: List[Dict[str, Any]], *, snapshot_price: bool = False) -> Dict[str, Any]:
    """Ingest multiple normalized messages; one Soul-Map batch sync at the end."""
    if not messages:
        return {"status": "error", "error": "Empty batch"}

    nlp, _price_tracker = _load_pipeline()
    db = get_db()
    processed: List[Dict[str, Any]] = []
    errors: List[str] = []
    from internal.message_intel.jury import evaluate_message

    for idx, payload in enumerate(messages):
        if not isinstance(payload, dict) or not payload.get("content"):
            errors.append(f"row {idx}: missing content")
            continue
        try:
            message_id, deduped = db.save_message(payload)
            if deduped:
                continue
            content = str(payload.get("content") or "")
            analysis = nlp.analyze(content)
            db.save_analysis(message_id, analysis)
            verdict = evaluate_message(message_id, content, analysis)
            db.save_verdict(message_id, verdict)
            processed.append(
                {
                    "message_id": message_id,
                    "payload": payload,
                    "analysis": analysis,
                    "verdict": verdict,
                }
            )
        except Exception as exc:
            errors.append(f"row {idx}: {exc}")

    soul = apply_batch_to_soul_map(batch_size=len(messages), records=processed)

    return {
        "status": "success" if processed else "error",
        "ingested": len(processed),
        "errors": errors,
        "soul_map": soul,
        "sources": source_status(),
    }


def list_messages(limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    from internal.message_intel.listener_service import listener_status

    db = get_db()
    messages = db.list_messages(limit=limit, offset=offset)
    meta = live_stats(db)
    meta["listener"] = listener_status()
    return {
        "status": "success",
        "count": len(messages),
        "messages": messages,
        "meta": meta,
        "sources": source_status(),
        "empty": len(messages) == 0,
    }


def get_message_detail(msg_id: int) -> Dict[str, Any]:
    db = get_db()
    message = db.get_message(msg_id)
    if message is None:
        return {"status": "error", "error": "Message not found"}
    return {"status": "success", "message": message}


def list_chatter(min_conviction: float = 60.0, limit: int = 50) -> Dict[str, Any]:
    db = get_db()
    messages = db.list_high_conviction_messages(min_conviction=min_conviction)
    return {
        "status": "success",
        "count": len(messages[:limit]),
        "messages": messages[:limit],
        "min_conviction": min_conviction,
    }


def list_patterns(limit: int = 20) -> Dict[str, Any]:
    db = get_db()
    patterns = db.list_patterns(limit=limit)
    return {
        "status": "success",
        "count": len(patterns),
        "patterns": patterns,
    }


def pipeline_health() -> Dict[str, Any]:
    stats = live_stats()
    sources = source_status()
    unavailable = []
    if not sources["telegram"]["configured"]:
        unavailable.append("telegram: TELEGRAM_API_ID/TELEGRAM_API_HASH not set")
    if not sources["discord"]["configured"]:
        unavailable.append("discord: DISCORD_BOT_TOKEN not set")
    return {
        "stats": stats,
        "sources": sources,
        "upstream_notes": unavailable,
    }
