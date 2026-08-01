"""Message-intel ingest engine — normalize, persist, Soul-Map, trail."""

from __future__ import annotations

import logging
import re
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
    return NLPAnalyzer(), PriceTracker()


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

    verdict = evaluate_message(message_id, content, analysis, author_id=payload.get("author_id"))
    db.save_verdict(message_id, verdict)

    price_result: Optional[Dict[str, Any]] = None
    if snapshot_price:
        try:
            from internal.message_intel.soul_sync import _extract_netuids

            price_tracker.db = db
            # Prefer subnet alpha snapshot when NLP found a netuid — more relevant
            # than TAO/USD and avoids an extra CoinGecko hit on every chat message.
            netuids = _extract_netuids(analysis)[:1]
            if netuids:
                subnet_snap = price_tracker.snapshot_subnet(message_id, netuids[0])
                if subnet_snap is not None:
                    price_result = {
                        "subnet_netuid": netuids[0],
                        "subnet_price": subnet_snap,
                    }
            if price_result is None:
                snap = price_tracker.snapshot(message_id)
                if snap is not None:
                    price_result = {"tao_usd_price": snap}
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
            verdict = evaluate_message(message_id, content, analysis, author_id=payload.get("author_id"))
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


def _registry_subnet_names() -> Dict[int, str]:
    """Canonical names for trending labels — no raw Unknown registry strings."""
    import json
    from pathlib import Path

    from internal.subnet_names import display_name_for_netuid

    try:
        raw = json.loads(Path("config/registry.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    names: Dict[int, str] = {}
    for key, row in raw.items():
        if not isinstance(row, dict):
            continue
        try:
            netuid = int(row.get("id", key))
        except (TypeError, ValueError):
            continue
        names[netuid] = display_name_for_netuid(netuid, use_taostats_fallback=False)
    return names


def _primary_netuid_from_message(row: Dict[str, Any]) -> Optional[int]:
    import json

    analysis = row.get("analysis") if isinstance(row.get("analysis"), dict) else {}
    entities = analysis.get("entities") if isinstance(analysis.get("entities"), dict) else {}
    if not entities and analysis.get("entities_json"):
        try:
            raw = analysis["entities_json"]
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, dict):
                entities = parsed
        except (TypeError, ValueError, json.JSONDecodeError):
            entities = {}
    for token in entities.get("subnets") or []:
        for num in re.findall(r"\d+", str(token)):
            try:
                return int(num)
            except ValueError:
                continue
    snap = row.get("price_snapshot") if isinstance(row.get("price_snapshot"), dict) else {}
    if snap.get("netuid") is not None:
        try:
            return int(snap["netuid"])
        except (TypeError, ValueError):
            pass
    return None


def _enrich_message_row(row: Dict[str, Any], names: Optional[Dict[int, str]] = None) -> Dict[str, Any]:
    """Attach top-level netuid/subnet_name so signal hub + UI can key off the row."""
    from internal.message_intel.topic_tags import classify_message_topics

    out = dict(row)
    if out.get("netuid") is None:
        netuid = _primary_netuid_from_message(out)
        if netuid is not None:
            out["netuid"] = netuid
            if names and not out.get("subnet_name"):
                out["subnet_name"] = names.get(netuid)
    content = out.get("content")
    if content and not out.get("topics"):
        out["topics"] = classify_message_topics(str(content))
    return out


def _message_matches_filters(
    row: Dict[str, Any],
    *,
    min_conviction: Optional[float],
    netuid: Optional[int],
    topic: Optional[str] = None,
) -> bool:
    if min_conviction is not None:
        verdict = row.get("verdict") if isinstance(row.get("verdict"), dict) else {}
        conv = verdict.get("conviction")
        if conv is None or float(conv) < min_conviction:
            return False
    if netuid is not None:
        row_netuid = row.get("netuid")
        if row_netuid is None or int(row_netuid) != int(netuid):
            return False
    if topic:
        topics = row.get("topics") if isinstance(row.get("topics"), list) else []
        if topic not in topics:
            return False
    return True


def list_messages(
    limit: int = 50,
    offset: int = 0,
    *,
    min_conviction: Optional[float] = None,
    netuid: Optional[int] = None,
    topic: Optional[str] = None,
) -> Dict[str, Any]:
    from internal.message_intel.listener_service import listener_status
    from internal.message_intel.rollup import (
        build_24h_summary,
        build_high_conviction_strip,
        build_reaction_crowns,
        build_telegram_proof_band,
        build_trending_subnets,
        build_week_top_comment,
        build_yesterday_leader,
    )

    db = get_db()
    names = _registry_subnet_names()
    filters_active = min_conviction is not None or netuid is not None or bool(topic)
    # ponytail: filtered queries scan recent 200 rows max — enough for desk feed, not full archive search
    fetch_limit = min(200, max(limit + offset, limit)) if filters_active else limit
    fetch_offset = 0 if filters_active else offset
    raw = db.list_messages(limit=fetch_limit, offset=fetch_offset)
    messages = [_enrich_message_row(m, names) for m in raw]
    if filters_active:
        messages = [
            m
            for m in messages
            if _message_matches_filters(
                m, min_conviction=min_conviction, netuid=netuid, topic=topic
            )
        ]
        messages = messages[offset : offset + limit]
    meta = live_stats(db)
    meta["listener"] = listener_status()
    try:
        trending = build_trending_subnets(registry_names=names, limit=8, db=db)
        trending_window = "1h"
        # Quiet hours: prefer a filled 24h board over an empty 1h panel.
        if not trending:
            trending = build_trending_subnets(
                registry_names=names, limit=8, db=db, rank_hours=24, window_hours=24
            )
            trending_window = "24h" if trending else "1h"
        meta["trending"] = trending
        meta["trending_window"] = trending_window
    except Exception as exc:
        logger.warning("message-intel trending rollup failed: %s", exc)
        meta["trending"] = []
        meta["trending_window"] = "1h"
    try:
        meta["yesterday_leader"] = build_yesterday_leader(
            registry_names=names, db=db
        )
    except Exception as exc:
        logger.warning("message-intel yesterday leader failed: %s", exc)
        meta["yesterday_leader"] = None
    try:
        meta["high_conviction_strip"] = build_high_conviction_strip(limit=5, db=db, registry_names=names)
    except Exception as exc:
        logger.warning("message-intel high conviction strip failed: %s", exc)
        meta["high_conviction_strip"] = []
    try:
        meta["telegram_proof"] = build_telegram_proof_band(db=db)
    except Exception as exc:
        logger.warning("message-intel telegram proof failed: %s", exc)
        meta["telegram_proof"] = {"graded": 0, "hits": 0, "hit_rate": None, "ready": False}
    try:
        meta["summary_24h"] = build_24h_summary(registry_names=names, db=db)
    except Exception as exc:
        logger.warning("message-intel 24h summary failed: %s", exc)
        meta["summary_24h"] = {
            "ready": False,
            "message_count": 0,
            "window_hours": 24,
            "empty_reason": "Summary unavailable.",
        }
    try:
        # Side feature — per-emoji weekly leaders; not call grading.
        meta["reaction_crowns"] = build_reaction_crowns(days=7, db=db)
    except Exception as exc:
        logger.warning("message-intel reaction crowns failed: %s", exc)
        meta["reaction_crowns"] = []
    try:
        # Side feature — single most-engaged comment this week.
        meta["week_top_comment"] = build_week_top_comment(days=7, db=db)
    except Exception as exc:
        logger.warning("message-intel week top comment failed: %s", exc)
        meta["week_top_comment"] = None
    if filters_active:
        applied: Dict[str, Any] = {}
        if min_conviction is not None:
            applied["min_conviction"] = min_conviction
        if netuid is not None:
            applied["netuid"] = netuid
        if topic:
            applied["topic"] = topic
        meta["filters"] = applied
    store_total = int(meta.get("total_messages") or 0)
    filtered_empty = filters_active and len(messages) == 0 and store_total > 0
    return {
        "status": "success",
        "count": len(messages),
        "messages": messages,
        "meta": meta,
        "sources": source_status(),
        "empty": len(messages) == 0,
        "filtered_empty": filtered_empty,
    }


def get_message_detail(msg_id: int) -> Dict[str, Any]:
    db = get_db()
    message = db.get_message(msg_id)
    if message is None:
        return {"status": "error", "error": "Message not found"}
    names = _registry_subnet_names()
    enriched = _enrich_message_row(message, names)
    verdict = enriched.get("verdict") if isinstance(enriched.get("verdict"), dict) else {}
    outcome = enriched.get("price_outcome") if isinstance(enriched.get("price_outcome"), dict) else {}
    snapshot = enriched.get("price_snapshot") if isinstance(enriched.get("price_snapshot"), dict) else {}
    graded = bool(outcome)
    return {
        "status": "success",
        "message": enriched,
        "detail": {
            "reasoning": verdict.get("reasoning"),
            "conviction": verdict.get("conviction"),
            "direction": verdict.get("predicted_direction"),
            "price_snapshot": snapshot,
            "price_outcome": outcome,
            "graded": graded,
            "netuid": enriched.get("netuid"),
            "subnet_name": enriched.get("subnet_name"),
        },
    }


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


def list_authors(*, days: int = 7, limit: int = 8) -> Dict[str, Any]:
    from internal.message_intel.rollup import build_reaction_crowns, build_weekly_authors

    try:
        authors = build_weekly_authors(days=days, limit=limit)
        try:
            crowns = build_reaction_crowns(days=days)
        except Exception as crown_exc:
            logger.warning("message-intel reaction crowns failed: %s", crown_exc)
            crowns = []
        return {
            "status": "success",
            "days": days,
            "count": len(authors),
            "authors": authors,
            "reaction_crowns": crowns,
            "empty": len(authors) == 0,
        }
    except Exception as exc:
        logger.error("message-intel authors failed: %s", exc)
        return {
            "status": "error",
            "authors": [],
            "reaction_crowns": [],
            "error": str(exc),
            "empty": True,
        }


def list_topics(*, limit: int = 12) -> Dict[str, Any]:
    from internal.message_intel.rollup import build_topics

    try:
        topics = build_topics(limit=limit)
        return {
            "status": "success",
            "count": len(topics),
            "topics": topics,
            "empty": len(topics) == 0,
        }
    except Exception as exc:
        logger.error("message-intel topics failed: %s", exc)
        return {"status": "error", "topics": [], "error": str(exc), "empty": True}


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
