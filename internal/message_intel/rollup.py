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


# Plus-feature crowns + light influence boost — not call grading.
_REACTION_KEYS = (
    ("fire", "🔥", "Hype"),
    ("hundred", "💯", "Facts"),
    ("heart", "❤️", "Love"),
    ("thumbs", "👍", "Agree"),
    ("rocket", "🚀", "Moon"),
)


def _reaction_score(raw: Any) -> Dict[str, int]:
    counts = {key: 0 for key, _, _ in _REACTION_KEYS}
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
        try:
            count = int(item.get("count") or 0)
        except (TypeError, ValueError):
            count = 0
        if count <= 0:
            continue
        if "🔥" in emoji:
            counts["fire"] += count
        elif "💯" in emoji or "100" in emoji:
            counts["hundred"] += count
        elif "🚀" in emoji:
            counts["rocket"] += count
        elif "❤" in emoji:
            counts["heart"] += count
        elif "👍" in emoji:
            counts["thumbs"] += count
    return counts


def _reaction_influence_boost(rx: Dict[str, int]) -> float:
    """Light social bump for champions — does not affect call hit-rate grading."""
    return float(
        rx.get("fire", 0) * 3
        + rx.get("hundred", 0) * 2
        + rx.get("rocket", 0) * 2
        + rx.get("heart", 0) * 2
        + rx.get("thumbs", 0) * 1
    )


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
    rank_hours: int = 1,
    db=None,
) -> List[Dict[str, Any]]:
    """Top subnets by mention volume in the rank window (default last hour) with sparkline buckets."""
    now = datetime.now(timezone.utc)
    rank_hours = max(1, int(rank_hours or 1))
    window_hours = max(rank_hours, int(window_hours or rank_hours))
    window_start = now - timedelta(hours=window_hours)
    rank_ago = now - timedelta(hours=rank_hours)
    prev_rank_ago = now - timedelta(hours=rank_hours * 2)
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
            if ts >= rank_ago:
                b["mentions_1h"] += 1
                b["sentiment_sum"] += s_val
                b["sentiment_n"] += 1
                b["conviction_sum"] += conviction
            elif ts >= prev_rank_ago:
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
                "window": f"{rank_hours}h",
            }
        )

    out.sort(key=lambda r: (r["heat"], r["mentions"], abs(r.get("change_1h", 0))), reverse=True)
    return out[:limit]


def build_yesterday_leader(
    *,
    registry_names: Optional[Dict[int, str]] = None,
    db=None,
) -> Optional[Dict[str, Any]]:
    """Subnet with the most mentions on the previous UTC calendar day."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)
    registry_names = registry_names or {}

    counts: Dict[int, Dict[str, Any]] = defaultdict(
        lambda: {"mentions": 0, "sentiment_sum": 0.0, "sentiment_n": 0}
    )

    for row in _load_message_rows(db):
        ts = _parse_ts(row.get("timestamp")) or _parse_ts(row.get("created_at"))
        if ts is None or ts < yesterday_start or ts >= today_start:
            continue
        netuids = _netuids_from_row(row)
        if not netuids:
            continue
        s_val = _sentiment_value(row.get("sentiment"))
        for netuid in netuids:
            c = counts[netuid]
            c["mentions"] += 1
            c["sentiment_sum"] += s_val
            c["sentiment_n"] += 1

    if not counts:
        return None

    ranked = sorted(
        counts.items(),
        key=lambda item: item[1]["mentions"],
        reverse=True,
    )
    top_netuid, top = ranked[0]
    avg = (top["sentiment_sum"] / top["sentiment_n"]) if top["sentiment_n"] else 0.0
    why_chips: List[str] = []
    proto_counts: Dict[str, int] = defaultdict(int)
    for row in _load_message_rows(db):
        ts = _parse_ts(row.get("timestamp")) or _parse_ts(row.get("created_at"))
        if ts is None or ts < yesterday_start or ts >= today_start:
            continue
        if top_netuid not in _netuids_from_row(row):
            continue
        raw = row.get("entities_json")
        try:
            entities = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (TypeError, json.JSONDecodeError):
            entities = {}
        for p in (entities or {}).get("protocols") or []:
            label = str(p).strip()
            if label:
                proto_counts[label] += 1
    for label, count in sorted(proto_counts.items(), key=lambda x: (-x[1], x[0]))[:3]:
        why_chips.append(label if count <= 1 else f"{label} ×{count}")

    out: Dict[str, Any] = {
        "netuid": top_netuid,
        "name": registry_names.get(top_netuid) or f"Subnet {top_netuid}",
        "mentions": int(top["mentions"]),
        "sentiment": _sentiment_tag(avg),
        "date": yesterday_start.date().isoformat(),
        "why_chips": why_chips,
    }
    if len(ranked) > 1:
        ru_netuid, ru = ranked[1]
        out["runner_up"] = {
            "netuid": ru_netuid,
            "name": registry_names.get(ru_netuid) or f"Subnet {ru_netuid}",
            "mentions": int(ru["mentions"]),
        }
    return out


def _author_outcome_stats(db=None) -> Dict[str, Dict[str, Any]]:
    """Map author_id → {graded, hits, hit_rate} from price_outcomes + verdicts."""
    database = db or get_db()
    stats: Dict[str, Dict[str, Any]] = {}
    try:
        with database._connect() as conn:
            rows = conn.execute(
                """SELECT m.author_id, m.author_username, m.author_name,
                          v.predicted_direction, po.outcome, po.pump_pct_max
                   FROM messages m
                   JOIN price_outcomes po ON po.message_id = m.id
                   LEFT JOIN message_verdicts v ON v.message_id = m.id"""
            ).fetchall()
    except Exception:
        return {}

    for row in rows:
        author_id = str(row["author_id"] or row["author_username"] or row["author_name"] or "unknown")
        entry = stats.setdefault(author_id, {"graded": 0, "hits": 0})
        entry["graded"] += 1
        direction = str(row["predicted_direction"] or "").lower()
        outcome = str(row["outcome"] or "").lower()
        hit = False
        if direction in ("up", "bullish") and outcome in ("pump", "mild_pump"):
            hit = True
        elif direction in ("down", "bearish") and outcome in ("dump", "mild_dump"):
            hit = True
        elif direction in ("flat", "sideways", "neutral", "") and outcome == "stable":
            hit = True
        elif outcome in ("pump", "mild_pump") and not direction:
            hit = True
        if hit:
            entry["hits"] += 1

    for entry in stats.values():
        graded = int(entry["graded"])
        hits = int(entry["hits"])
        entry["hit_rate"] = round((hits / graded) * 100.0, 1) if graded else None
    return stats


def build_weekly_authors(*, days: int = 7, limit: int = 8, db=None) -> List[Dict[str, Any]]:
    """Top contributors by emoji-weighted influence over the last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    authors: Dict[str, Dict[str, Any]] = {}
    outcome_stats = _author_outcome_stats(db)

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
                "reactions": {key: 0 for key, _, _ in _REACTION_KEYS},
            },
        )
        entry["message_count"] += 1
        entry["influence_score"] += float(row.get("influence_score") or 0.0)
        for netuid in _netuids_from_row(row):
            entry["subnets"].add(netuid)
        rx = _reaction_score(row.get("reactions"))
        for key, _, _ in _REACTION_KEYS:
            entry["reactions"][key] += rx[key]
        # Optional light boost only — call hit-rate stays separate.
        entry["influence_score"] += _reaction_influence_boost(rx)

    out: List[Dict[str, Any]] = []
    for entry in authors.values():
        if entry["message_count"] <= 0:
            continue
        name = str(entry["author_name"] or "Unknown")
        initials = "".join(part[0].upper() for part in name.split()[:2]) or "?"
        graded = outcome_stats.get(entry["author_id"]) or {}
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
                "graded": int(graded.get("graded") or 0),
                "hits": int(graded.get("hits") or 0),
                "hit_rate": graded.get("hit_rate"),
            }
        )

    out.sort(key=lambda r: (r["influence_score"], r["message_count"]), reverse=True)
    return out[:limit]


def build_reaction_crowns(*, days: int = 7, db=None) -> List[Dict[str, Any]]:
    """Per-emoji weekly leaders — social plus feature, not call grading."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    # key → author_id → {count, author_name, author_username}
    tallies: Dict[str, Dict[str, Dict[str, Any]]] = {
        key: {} for key, _, _ in _REACTION_KEYS
    }

    for row in _load_message_rows(db):
        ts = _parse_ts(row.get("timestamp")) or _parse_ts(row.get("created_at"))
        if ts is None or ts < cutoff:
            continue
        rx = _reaction_score(row.get("reactions"))
        if not any(rx.values()):
            continue
        author_id = str(
            row.get("author_id") or row.get("author_username") or row.get("author_name") or "unknown"
        )
        name = row.get("author_name") or "Unknown"
        username = row.get("author_username") or ""
        for key, _, _ in _REACTION_KEYS:
            n = int(rx.get(key) or 0)
            if n <= 0:
                continue
            entry = tallies[key].setdefault(
                author_id,
                {
                    "author_id": author_id,
                    "author_name": name,
                    "author_username": username,
                    "count": 0,
                },
            )
            entry["count"] += n
            entry["author_name"] = name or entry["author_name"]
            if username:
                entry["author_username"] = username

    crowns: List[Dict[str, Any]] = []
    for key, emoji, label in _REACTION_KEYS:
        bucket = tallies[key]
        if not bucket:
            continue
        winner = max(bucket.values(), key=lambda e: (int(e["count"]), str(e["author_name"])))
        if int(winner["count"]) <= 0:
            continue
        handle = str(winner.get("author_username") or "").lstrip("@")
        display = f"@{handle}" if handle else str(winner.get("author_name") or "Unknown")
        crowns.append(
            {
                "key": key,
                "emoji": emoji,
                "label": label,
                "author_id": winner["author_id"],
                "author_name": winner["author_name"],
                "author_username": winner.get("author_username") or "",
                "display_name": display,
                "count": int(winner["count"]),
                "days": days,
            }
        )
    return crowns


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


def _outcome_hit(direction: str, outcome: str) -> bool:
    direction = str(direction or "").lower()
    outcome = str(outcome or "").lower()
    if direction in ("up", "bullish", "long", "buy") and outcome in ("pump", "mild_pump"):
        return True
    if direction in ("down", "bearish", "short", "sell") and outcome in ("dump", "mild_dump"):
        return True
    if direction in ("flat", "sideways", "neutral", "") and outcome == "stable":
        return True
    if outcome in ("pump", "mild_pump") and not direction:
        return True
    return False


def build_telegram_proof_band(*, db=None) -> Dict[str, Any]:
    """SS-TG W3 — graded Telegram call hit-rate for proof strip."""
    database = db or get_db()
    graded = 0
    hits = 0
    recent: List[Dict[str, Any]] = []
    try:
        with database._connect() as conn:
            rows = conn.execute(
                """SELECT m.id, m.author_name, m.timestamp, v.predicted_direction, v.conviction,
                          po.outcome, po.pump_pct_max, ps.netuid
                   FROM messages m
                   JOIN price_outcomes po ON po.message_id = m.id
                   LEFT JOIN message_verdicts v ON v.message_id = m.id
                   LEFT JOIN price_snapshots ps ON ps.message_id = m.id
                   WHERE m.source = 'telegram'
                   ORDER BY m.id DESC
                   LIMIT 200"""
            ).fetchall()
    except Exception:
        return {"graded": 0, "hits": 0, "hit_rate": None, "ready": False, "recent": []}

    for row in rows:
        graded += 1
        direction = str(row["predicted_direction"] or "")
        outcome = str(row["outcome"] or "")
        if _outcome_hit(direction, outcome):
            hits += 1
        if len(recent) < 4:
            recent.append(
                {
                    "id": int(row["id"]),
                    "author_name": row["author_name"],
                    "outcome": outcome,
                    "pump_pct_max": row["pump_pct_max"],
                    "netuid": row["netuid"],
                    "hit": _outcome_hit(direction, outcome),
                }
            )

    hit_rate = round((hits / graded) * 100.0, 1) if graded else None
    return {
        "graded": graded,
        "hits": hits,
        "hit_rate": hit_rate,
        "ready": graded >= 3,
        "recent": recent,
    }


_MIN_24H_SUMMARY_MESSAGES = 10


def build_24h_summary(
    *,
    registry_names: Optional[Dict[int, str]] = None,
    limit: int = 5,
    min_conviction: float = 60.0,
    db=None,
) -> Dict[str, Any]:
    """SS-TG W4 — last-24h rollup: top subnets, movers, HC count, group pulse."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=24)
    prev_start = now - timedelta(hours=48)
    registry_names = registry_names or {}

    message_count = 0
    hc_count = 0
    sentiment_sum = 0.0
    sentiment_n = 0
    conviction_sum = 0.0
    subnet_counts: Dict[int, int] = defaultdict(int)
    prev_subnet_counts: Dict[int, int] = defaultdict(int)
    group_counts: Dict[str, int] = defaultdict(int)

    for row in _load_message_rows(db):
        ts = _parse_ts(row.get("timestamp")) or _parse_ts(row.get("created_at"))
        if ts is None or ts < prev_start:
            continue
        in_current = ts >= window_start
        in_prev = prev_start <= ts < window_start
        if not in_current and not in_prev:
            continue

        if in_current:
            message_count += 1
            s_val = _sentiment_value(row.get("sentiment"))
            sentiment_sum += s_val
            sentiment_n += 1
            try:
                conviction = float(row.get("conviction") or 0)
            except (TypeError, ValueError):
                conviction = 0.0
            conviction_sum += conviction
            if conviction >= min_conviction:
                hc_count += 1
            group = str(row.get("group_name") or "").strip()
            if group:
                group_counts[group] += 1
            for netuid in _netuids_from_row(row):
                subnet_counts[netuid] += 1

        if in_prev:
            for netuid in _netuids_from_row(row):
                prev_subnet_counts[netuid] += 1

    base: Dict[str, Any] = {
        "window_hours": 24,
        "message_count": message_count,
        "ready": message_count >= _MIN_24H_SUMMARY_MESSAGES,
    }
    if message_count < _MIN_24H_SUMMARY_MESSAGES:
        base["empty_reason"] = (
            f"Only {message_count} message{'s' if message_count != 1 else ''} in the last 24h — "
            f"summary needs at least {_MIN_24H_SUMMARY_MESSAGES}."
        )
        base["min_messages"] = _MIN_24H_SUMMARY_MESSAGES
        return base

    avg_sent = (sentiment_sum / sentiment_n) if sentiment_n else 0.0
    avg_conv = (conviction_sum / message_count) if message_count else 0.0

    top_subnets: List[Dict[str, Any]] = []
    for netuid, mentions in sorted(subnet_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]:
        top_subnets.append(
            {
                "netuid": netuid,
                "name": registry_names.get(netuid) or f"Subnet {netuid}",
                "mentions": int(mentions),
            }
        )

    movers: List[Dict[str, Any]] = []
    for netuid in set(subnet_counts) | set(prev_subnet_counts):
        cur = int(subnet_counts.get(netuid, 0))
        prev = int(prev_subnet_counts.get(netuid, 0))
        if cur <= 0:
            continue
        movers.append(
            {
                "netuid": netuid,
                "name": registry_names.get(netuid) or f"Subnet {netuid}",
                "mentions": cur,
                "prev_mentions": prev,
                "change": cur - prev,
            }
        )
    movers.sort(key=lambda r: (r["change"], r["mentions"]), reverse=True)

    group_pulse: Dict[str, Any] = {
        "messages": message_count,
        "high_conviction": hc_count,
        "sentiment": _sentiment_tag(avg_sent),
        "avg_conviction": round(avg_conv, 1),
    }
    if group_counts:
        top_group, top_count = max(group_counts.items(), key=lambda kv: kv[1])
        group_pulse["group"] = top_group
        group_pulse["top_group_messages"] = int(top_count)
        group_pulse["groups_active"] = len(group_counts)

    return {
        **base,
        "top_subnets": top_subnets,
        "movers": movers[:limit],
        "high_conviction_count": hc_count,
        "group_pulse": group_pulse,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
    }


def build_high_conviction_strip(
    *,
    limit: int = 5,
    min_conviction: float = 60.0,
    db=None,
    registry_names: Optional[Dict[int, str]] = None,
) -> List[Dict[str, Any]]:
    """SS-TG W2 — top high-conviction Telegram rows for the strip."""
    database = db or get_db()
    names = registry_names or {}
    try:
        rows = database.list_high_conviction_messages(min_conviction=min_conviction)
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    for row in rows[:limit]:
        verdict = row.get("verdict") if isinstance(row.get("verdict"), dict) else {}
        analysis = row.get("analysis") if isinstance(row.get("analysis"), dict) else {}
        conviction = verdict.get("conviction") if verdict else row.get("conviction")
        direction = verdict.get("predicted_direction") if verdict else row.get("predicted_direction")
        netuid = None
        try:
            entities = json.loads(analysis.get("entities_json") or "{}")
            for token in entities.get("subnets") or []:
                for num in re.findall(r"\d+", str(token)):
                    netuid = int(num)
                    break
                if netuid is not None:
                    break
        except Exception:
            pass
        out.append(
            {
                "id": row.get("id"),
                "author_name": row.get("author_name"),
                "content": row.get("content"),
                "conviction": conviction,
                "direction": direction,
                "netuid": netuid,
                "subnet_name": names.get(netuid) if netuid is not None else None,
            }
        )
    return out
