"""Trending subnets + weekly author leaderboard rollups for message-intel UI."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from internal.message_intel.store import get_db

_EMOJI_WEIGHTS = {"🔥": 3, "❤": 2, "❤️": 2, "👍": 1, "🚀": 2, "💯": 2}
_SENTIMENT_LABEL = {1.0: "Bullish", 0.0: "Cautious", -1.0: "Bearish"}


def _parse_ts(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _netuids_from_row(row: Dict[str, Any]) -> Set[int]:
    found: Set[int] = set()
    if row.get("snap_netuid") is not None:
        found.add(int(row["snap_netuid"]))
    raw = row.get("entities_json")
    if not raw:
        return found
    try:
        entities = json.loads(raw) if isinstance(raw, str) else raw
        for token in (entities or {}).get("subnets") or []:
            for num in re.findall(r"\d+", str(token)):
                found.add(int(num))
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return found


def _sentiment_value(label: Optional[str]) -> float:
    s = str(label or "neutral").lower()
    if s in ("bullish", "positive"):
        return 1.0
    if s in ("bearish", "negative"):
        return -1.0
    return 0.0


def _sentiment_tag(avg: float) -> str:
    if avg > 0.2:
        return "Bullish"
    if avg < -0.2:
        return "Bearish"
    return "Cautious"


def _reaction_score(raw: Any) -> Dict[str, int]:
    counts = {"fire": 0, "heart": 0, "thumbs": 0}
    items: List[Any] = []
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list):
            items = parsed
        elif isinstance(parsed, dict):
            items = [{"emoji": k, "count": v} for k, v in parsed.items()]
    elif isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = [{"emoji": k, "count": v} for k, v in raw.items()]

    for item in items:
        if not isinstance(item, dict):
            continue
        emoji = str(item.get("emoji") or item.get("emoticon") or "")
        count = int(item.get("count") or 0)
        if "🔥" in emoji:
            counts["fire"] += count
        elif "❤" in emoji:
            counts["heart"] += count
        elif "👍" in emoji:
            counts["thumbs"] += count
    return counts


def _load_message_rows(db=None) -> List[Dict[str, Any]]:
    database = db or get_db()
    with database._connect() as conn:
        rows = conn.execute(
            """SELECT m.id, m.author_id, m.author_name, m.author_username, m.group_name,
                      m.timestamp, m.created_at, a.sentiment, a.influence_score, a.entities_json,
                      mm.reactions, ps.netuid AS snap_netuid, v.conviction
               FROM messages m
               LEFT JOIN message_analysis a ON a.message_id = m.id
               LEFT JOIN message_metrics mm ON mm.message_id = m.id
               LEFT JOIN price_snapshots ps ON ps.message_id = m.id
               LEFT JOIN message_verdicts v ON v.message_id = m.id
               ORDER BY m.id DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def build_trending_subnets(
    *,
    registry_names: Optional[Dict[int, str]] = None,
    limit: int = 8,
    window_hours: int = 6,
    db=None,
) -> List[Dict[str, Any]]:
    """Top subnets by mention volume in the last hour with sparkline buckets."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=window_hours)
    hour_ago = now - timedelta(hours=1)
    two_hours_ago = now - timedelta(hours=2)
    registry_names = registry_names or {}

    buckets: Dict[int, Dict[str, Any]] = defaultdict(
        lambda: {
            "mentions_1h": 0,
            "mentions_prev_1h": 0,
            "sentiment_sum": 0.0,
            "sentiment_n": 0,
            "conviction_sum": 0.0,
            "spark": [0] * window_hours,
        }
    )

    for row in _load_message_rows(db):
        ts = _parse_ts(row.get("timestamp")) or _parse_ts(row.get("created_at"))
        if ts is None or ts < window_start:
            continue
        netuids = _netuids_from_row(row)
        if not netuids:
            continue
        hour_idx = int((ts - window_start).total_seconds() // 3600)
        hour_idx = max(0, min(window_hours - 1, hour_idx))
        s_val = _sentiment_value(row.get("sentiment"))
        try:
            conviction = float(row.get("conviction") or 0)
        except (TypeError, ValueError):
            conviction = 0.0
        for netuid in netuids:
            b = buckets[netuid]
            b["spark"][hour_idx] += 1
            if ts >= hour_ago:
                b["mentions_1h"] += 1
                b["sentiment_sum"] += s_val
                b["sentiment_n"] += 1
                b["conviction_sum"] += conviction
            elif ts >= two_hours_ago:
                b["mentions_prev_1h"] += 1

    out: List[Dict[str, Any]] = []
    for netuid, b in buckets.items():
        mentions = int(b["mentions_1h"])
        if mentions <= 0:
            continue
        prev = int(b["mentions_prev_1h"])
        change = mentions - prev
        avg = (b["sentiment_sum"] / b["sentiment_n"]) if b["sentiment_n"] else 0.0
        avg_conv = (b["conviction_sum"] / mentions) if mentions else 0.0
        # Rank by chatter × conviction so fluff spam doesn't dominate.
        heat = mentions * (1.0 + avg_conv / 100.0)
        out.append(
            {
                "netuid": netuid,
                "name": registry_names.get(netuid) or f"Subnet {netuid}",
                "mentions": mentions,
                "change_1h": change,
                "sentiment": _sentiment_tag(avg),
                "avg_conviction": round(avg_conv, 1),
                "heat": round(heat, 3),
                "sparkline": list(b["spark"]),
            }
        )

    out.sort(key=lambda r: (r["heat"], r["mentions"], abs(r.get("change_1h", 0))), reverse=True)
    return out[:limit]


def build_weekly_authors(*, days: int = 7, limit: int = 8, db=None) -> List[Dict[str, Any]]:
    """Top contributors by emoji-weighted influence over the last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    authors: Dict[str, Dict[str, Any]] = {}

    for row in _load_message_rows(db):
        ts = _parse_ts(row.get("timestamp")) or _parse_ts(row.get("created_at"))
        if ts is None or ts < cutoff:
            continue
        author_id = str(row.get("author_id") or row.get("author_username") or row.get("author_name") or "unknown")
        entry = authors.setdefault(
            author_id,
            {
                "author_id": author_id,
                "author_name": row.get("author_name") or "Unknown",
                "author_username": row.get("author_username") or "",
                "message_count": 0,
                "influence_score": 0.0,
                "subnets": set(),
                "reactions": {"fire": 0, "heart": 0, "thumbs": 0},
            },
        )
        entry["message_count"] += 1
        entry["influence_score"] += float(row.get("influence_score") or 0.0)
        for netuid in _netuids_from_row(row):
            entry["subnets"].add(netuid)
        rx = _reaction_score(row.get("reactions"))
        for key in ("fire", "heart", "thumbs"):
            entry["reactions"][key] += rx[key]
        entry["influence_score"] += rx["fire"] * 3 + rx["heart"] * 2 + rx["thumbs"] * 1

    out: List[Dict[str, Any]] = []
    for entry in authors.values():
        if entry["message_count"] <= 0:
            continue
        name = str(entry["author_name"] or "Unknown")
        initials = "".join(part[0].upper() for part in name.split()[:2]) or "?"
        out.append(
            {
                "author_id": entry["author_id"],
                "author_name": name,
                "author_username": entry["author_username"],
                "initials": initials[:2],
                "message_count": int(entry["message_count"]),
                "subnet_count": len(entry["subnets"]),
                "influence_score": round(float(entry["influence_score"]), 2),
                "reactions": dict(entry["reactions"]),
            }
        )

    out.sort(key=lambda r: (r["influence_score"], r["message_count"]), reverse=True)
    return out[:limit]


def build_topics(*, limit: int = 12, db=None) -> List[Dict[str, Any]]:
    """Lightweight topic rollup: monitored groups + hot subnets."""
    group_counts: Dict[str, int] = defaultdict(int)
    subnet_counts: Dict[int, int] = defaultdict(int)

    for row in _load_message_rows(db):
        group = str(row.get("group_name") or "").strip()
        if group:
            group_counts[group] += 1
        for netuid in _netuids_from_row(row):
            subnet_counts[netuid] += 1

    topics: List[Dict[str, Any]] = []
    for name, count in sorted(group_counts.items(), key=lambda kv: kv[1], reverse=True)[: limit // 2]:
        topics.append({"kind": "group", "label": name, "mentions": count})
    for netuid, count in sorted(subnet_counts.items(), key=lambda kv: kv[1], reverse=True)[: limit // 2]:
        topics.append({"kind": "subnet", "label": f"SN{netuid}", "netuid": netuid, "mentions": count})
    topics.sort(key=lambda r: r["mentions"], reverse=True)
    return topics[:limit]
