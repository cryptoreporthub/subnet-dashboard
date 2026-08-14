"""Trending subnets + weekly author leaderboard rollups for message-intel UI."""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from internal.message_intel.store import get_db
from internal.message_intel.proof import (
    MIN_LEADERBOARD_SAMPLE,
    classify_call,
    resolve_direction,
    stable_author_id,
)

logger = logging.getLogger(__name__)

_EMOJI_WEIGHTS = {"🔥": 3, "❤": 2, "❤️": 2, "👍": 1, "🚀": 2, "💯": 2}
_SENTIMENT_LABEL = {1.0: "Bullish", 0.0: "Cautious", -1.0: "Bearish"}

# Public Telegram consensus methodology.  These constants are deliberately
# conservative: the signal is a small, auditable evidence layer, not a proxy
# for a trading recommendation.
CONVICTION_WINDOW_HOURS = 72
CONVICTION_HALF_LIFE_HOURS = 24
CONVICTION_MIN_CALLS = 2
CONVICTION_MIN_CONTRIBUTORS = 2
CONVICTION_MIN_AUTHOR_SAMPLE = MIN_LEADERBOARD_SAMPLE
CONVICTION_MIN_JURY_SCORE = 60.0

# Divergence stories are deliberately a compact, evidence-only read of
# timestamped Telegram calls.  They are not a forecast model: every included
# receipt has its own recorded 24h outcome and the rollup never uses
# engagement, sentiment, or non-Telegram sources.
DIVERGENCE_DEFAULT_DAYS = 7
DIVERGENCE_MAX_DAYS = 30
DIVERGENCE_MIN_CALLS = 2
DIVERGENCE_MIN_CONTRIBUTORS = 2


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
                      m.timestamp, m.created_at, m.content, a.sentiment, a.influence_score, a.entities_json,
                      mm.reactions, ps.netuid AS snap_netuid, v.conviction
               FROM messages m
               LEFT JOIN message_analysis a ON a.message_id = m.id
               LEFT JOIN message_metrics mm ON mm.message_id = m.id
               LEFT JOIN price_snapshots ps ON ps.message_id = m.id
               LEFT JOIN message_verdicts v ON v.message_id = m.id
               ORDER BY m.id DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _author_rolling_quality(stats: Dict[str, Any]) -> float:
    graded = max(0, _coerce_int(stats.get("graded") or stats.get("total_messages")))
    hits = max(0, _coerce_int(stats.get("hits") or stats.get("correct_predictions")))
    if graded <= 0:
        return 0.5
    return (min(hits, graded) + 2.0) / (graded + 4.0)




def build_trending_subnets(
    *,
    registry_names: Optional[Dict[int, str]] = None,
    limit: int = 8,
    window_hours: int = 6,
    rank_hours: int = 1,
    db=None,
) -> List[Dict[str, Any]]:
    """Top subnets by ChatterPower over the rank window with sparkline buckets."""
    now = datetime.now(timezone.utc)
    rank_hours = max(1, int(rank_hours or 1))
    window_hours = max(rank_hours, int(window_hours or rank_hours))
    window_start = now - timedelta(hours=window_hours)
    rank_ago = now - timedelta(hours=rank_hours)
    prev_rank_ago = now - timedelta(hours=rank_hours * 2)
    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(hours=24)
    lookback_start = now - timedelta(hours=max(window_hours, rank_hours * 2, 24))
    registry_names = registry_names or {}

    buckets: Dict[int, Dict[str, Any]] = defaultdict(
        lambda: {
            "rank": {"mentions": 0, "sentiment_sum": 0.0, "conviction_sum": 0.0, "author_ids": set()},
            "prev": {"mentions": 0, "sentiment_sum": 0.0, "conviction_sum": 0.0, "author_ids": set()},
            "hour": {"mentions": 0, "sentiment_sum": 0.0, "conviction_sum": 0.0, "author_ids": set()},
            "day": {"mentions": 0, "sentiment_sum": 0.0, "conviction_sum": 0.0, "author_ids": set()},
            "spark": [0] * window_hours,
        }
    )

    for row in _load_message_rows(db):
        ts = _parse_ts(row.get("timestamp")) or _parse_ts(row.get("created_at"))
        if ts is None or ts < lookback_start:
            continue
        s_val = _sentiment_value(row.get("sentiment"))
        conviction = _coerce_float(row.get("conviction"))
        author_id = stable_author_id(row)
        netuids = _netuids_from_row(row)
        for netuid in netuids:
            b = buckets[netuid]
            if ts >= rank_ago:
                bucket = b["rank"]
                bucket["mentions"] += 1
                bucket["sentiment_sum"] += s_val
                bucket["conviction_sum"] += conviction
                bucket["author_ids"].add(author_id)
            elif ts >= prev_rank_ago:
                bucket = b["prev"]
                bucket["mentions"] += 1
                bucket["sentiment_sum"] += s_val
                bucket["conviction_sum"] += conviction
                bucket["author_ids"].add(author_id)
            if ts >= hour_ago:
                bucket = b["hour"]
                bucket["mentions"] += 1
                bucket["sentiment_sum"] += s_val
                bucket["conviction_sum"] += conviction
                bucket["author_ids"].add(author_id)
            if ts >= day_ago:
                bucket = b["day"]
                bucket["mentions"] += 1
                bucket["sentiment_sum"] += s_val
                bucket["conviction_sum"] += conviction
                bucket["author_ids"].add(author_id)
            if ts >= window_start:
                hour_idx = int((ts - window_start).total_seconds() // 3600)
                hour_idx = max(0, min(window_hours - 1, hour_idx))
                b["spark"][hour_idx] += 1

    out: List[Dict[str, Any]] = []
    reliability_rows = _author_reliability_rows(db)
    for netuid, b in buckets.items():
        rank = b["rank"]
        mentions = int(rank["mentions"])
        if mentions <= 0:
            continue
        def window_metrics(bucket: Dict[str, Any], hours: int) -> Dict[str, float]:
            count = int(bucket["mentions"])
            avg_sentiment = bucket["sentiment_sum"] / count if count else 0.0
            avg_conviction = bucket["conviction_sum"] / count if count else 0.0
            qualities = [
                _author_rolling_quality(reliability_rows.get(aid, {}))
                for aid in bucket["author_ids"]
            ]
            quality_value = sum(qualities) / len(qualities) if qualities else 0.5
            velocity_value = count / max(hours, 1)
            conviction_value = max(0.0, avg_conviction / 100.0)
            power = velocity_value * conviction_value * max(0.1, quality_value)
            return {
                "mentions": count,
                "sentiment": avg_sentiment,
                "conviction": avg_conviction,
                "quality": quality_value,
                "velocity": velocity_value,
                "power": power,
            }

        current = window_metrics(rank, rank_hours)
        previous = window_metrics(b["prev"], rank_hours)
        hourly = window_metrics(b["hour"], 1)
        daily = window_metrics(b["day"], 24)
        chatter_power = current["power"]
        prev_power = previous["power"]
        quality = current["quality"]
        velocity = current["velocity"]
        avg_conv = current["conviction"]
        avg = current["sentiment"]
        delta = chatter_power - prev_power
        why = f"velocity {velocity:.2f} × conviction {current['conviction'] / 100.0:.2f} × quality {quality:.2f}"
        out.append(
            {
                "netuid": netuid,
                "name": registry_names.get(netuid) or f"Subnet {netuid}",
                "mentions": mentions,
                "velocity": round(velocity, 3),
                "conviction": round(avg_conv, 1),
                "quality": round(quality, 3),
                "chatter_power": round(chatter_power, 4),
                "delta": round(delta, 4),
                "movement_1h": round(hourly["power"], 4),
                "movement_24h": round(daily["power"], 4),
                "sentiment": _sentiment_tag(avg),
                "avg_conviction": round(avg_conv, 1),
                "heat": round(chatter_power, 3),
                "sparkline": list(b["spark"]),
                "window": f"{rank_hours}h",
                "why": why,
            }
        )

    out.sort(key=lambda r: (r["chatter_power"], r["mentions"], abs(r.get("delta", 0))), reverse=True)
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


def _author_outcome_stats(db=None, *, days: Optional[int] = None) -> Dict[str, Dict[str, Any]]:
    """Map author_id → canonical resolved hit/miss stats."""
    stats: Dict[str, Dict[str, Any]] = {}
    try:
        rows = _proof_rows(db, days=days)
    except Exception:
        return {}

    from internal.message_intel.proof import classify_call

    for row in rows:
        proof = classify_call(row)
        if not proof.get("eligible") or proof.get("status") not in {"hit", "miss"}:
            continue
        author_id = stable_author_id(row)
        entry = stats.setdefault(author_id, {"graded": 0, "hits": 0})
        entry["graded"] += 1
        if proof.get("status") == "hit":
            entry["hits"] += 1

    for entry in stats.values():
        graded = int(entry["graded"])
        hits = int(entry["hits"])
        entry["hit_rate"] = round((hits / graded) * 100.0, 1) if graded else None
        entry["strike_rate"] = entry["hit_rate"]
        entry["correct_predictions"] = hits
        entry["total_graded_calls"] = graded
        entry["caution"] = graded < 5
    return stats


def _author_reliability_rows(db=None) -> Dict[str, Dict[str, Any]]:
    """Read the persisted per-author strike-rate ledger."""
    database = db or get_db()
    try:
        with database._connect() as conn:
            rows = conn.execute(
                """SELECT author_id, author_name, total_messages,
                          correct_predictions, accuracy_score
                   FROM author_reliability"""
            ).fetchall()
    except Exception:
        return {}

    result: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        raw_id = str(row["author_id"])
        record = {
            "author_id": str(row["author_id"]),
            "author_name": row["author_name"],
            "total_messages": max(0, int(row["total_messages"] or 0)),
            "correct_predictions": max(0, int(row["correct_predictions"] or 0)),
            "accuracy_score": float(row["accuracy_score"] or 0.0),
        }
        if not raw_id:
            continue
        result[raw_id] = record
        # The persisted ledger predates the prefixed stable-author contract.
        # Keep a compatibility alias until historical rows are backfilled.
        if not raw_id.startswith(("id:", "u:", "n:")):
            result.setdefault(f"id:{raw_id}", record)
    return result


def build_weekly_authors(*, days: int = 7, limit: int = 8, db=None) -> List[Dict[str, Any]]:
    """Top contributors by emoji-weighted influence over the last N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    authors: Dict[str, Dict[str, Any]] = {}
    outcome_stats = _author_outcome_stats(db, days=days)
    reliability_rows = _author_reliability_rows(db)

    for row in _load_message_rows(db):
        ts = _parse_ts(row.get("timestamp")) or _parse_ts(row.get("created_at"))
        if ts is None or ts < cutoff:
            continue
        author_id = stable_author_id(row)
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
        persisted = reliability_rows.get(entry["author_id"])
        persisted_total = persisted["total_messages"] if persisted else 0
        persisted_hits = min(persisted["correct_predictions"], persisted_total) if persisted else 0
        canonical_graded = int(graded.get("graded") or 0)
        canonical_caution = canonical_graded > 0 and canonical_graded < 5
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
                "strike_rate": graded.get("strike_rate"),
                "correct_predictions": int(graded.get("correct_predictions") or 0),
                "total_graded_calls": int(graded.get("total_graded_calls") or 0),
                "caution": canonical_caution or (canonical_graded == 0 and 0 < persisted_total < 5),
                "reliability_total_messages": persisted_total,
                "reliability_correct_predictions": persisted_hits,
                "reliability_accuracy_pct": (
                    round((persisted_hits / persisted_total) * 100.0, 1)
                    if persisted_total else None
                ),
                "receipt_friendly": {
                    "author_id": entry["author_id"],
                    "author_name": name,
                    "author_username": entry["author_username"],
                    "available": canonical_graded > 0,
                    "graded": canonical_graded,
                    "hit_rate": graded.get("hit_rate") if canonical_graded else None,
                    "strike_rate": graded.get("strike_rate") if canonical_graded else None,
                },
            }
        )

    out.sort(key=lambda r: (r["influence_score"], r["message_count"]), reverse=True)
    return out[:limit]


def build_author_reliability_rows(*, days: int = 7, limit: int = 8, db=None) -> List[Dict[str, Any]]:
    """Expose SQLite-backed author reliability with strike-rate fields."""
    rows = build_weekly_authors(days=days, limit=max(limit, 50), db=db)
    reliability_rows = _author_reliability_rows(db)
    present_ids = {str(row.get("author_id")) for row in rows}
    for author_id, persisted in reliability_rows.items():
        if author_id in present_ids:
            continue
        total = persisted["total_messages"]
        hits = min(persisted["correct_predictions"], total)
        name = str(persisted.get("author_name") or "Unknown")
        rows.append(
            {
                "author_id": author_id,
                "author_name": name,
                "author_username": "",
                "initials": "".join(part[0].upper() for part in name.split()[:2]) or "?",
                "message_count": 0,
                "subnet_count": 0,
                "influence_score": 0.0,
                "reactions": {key: 0 for key, _, _ in _REACTION_KEYS},
                "graded": total,
                "hits": hits,
                "hit_rate": round((hits / total) * 100.0, 1) if total else None,
                "strike_rate": round((hits / total) * 100.0, 1) if total else None,
                "correct_predictions": hits,
                "total_graded_calls": total,
                "caution": total < 5,
                "receipt_friendly": {
                    "author_id": author_id,
                    "author_name": name,
                    "author_username": "",
                    "graded": total,
                    "hit_rate": round((hits / total) * 100.0, 1) if total else None,
                    "strike_rate": round((hits / total) * 100.0, 1) if total else None,
                },
            }
        )
    out: List[Dict[str, Any]] = []
    for row in rows:
        graded = int(row.get("graded") or 0)
        hits = int(row.get("hits") or 0)
        strike_rate = row.get("strike_rate")
        if strike_rate is None and graded:
            strike_rate = round((hits / graded) * 100.0, 1)
        reliability_total = int(row.get("reliability_total_messages") or 0)
        reliability_hits = int(row.get("reliability_correct_predictions") or 0)
        reliability_rate = row.get("reliability_accuracy_pct")
        display_total = graded or reliability_total
        display_hits = hits if graded else reliability_hits
        display_rate = strike_rate if graded else reliability_rate
        out.append(
            {
                **row,
                "accuracy_pct": display_rate,
                "strike_rate_pct": display_rate,
                "correct_predictions": int(row.get("correct_predictions") or display_hits),
                "total_graded_calls": int(row.get("total_graded_calls") or display_total),
                "stats_source": "proof_contract" if graded else (
                    "author_reliability" if reliability_total else "none"
                ),
                "caution": bool(row.get("caution")) if graded else (
                    0 < reliability_total < 5
                ),
                "graded_calls_caution": bool(row.get("caution")) if graded else (
                    0 < reliability_total < 5
                ),
            }
        )
    out.sort(key=lambda r: (r["influence_score"], r["message_count"], r["total_graded_calls"]), reverse=True)
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
        author_id = stable_author_id(row)
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


def _reaction_total(raw: Any) -> int:
    return int(sum(_reaction_score(raw).values()))


def _top_reaction(raw: Any) -> Optional[Dict[str, Any]]:
    rx = _reaction_score(raw)
    if not any(rx.values()):
        return None
    key, count = max(rx.items(), key=lambda kv: kv[1])
    emoji = next((e for k, e, _ in _REACTION_KEYS if k == key), "")
    return {"key": key, "emoji": emoji, "count": int(count)}


def _engagement_why(views: int, forwards: int, reaction_total: int, replies: int) -> str:
    """Name the dominant engagement signal for the UI eyebrow."""
    weighted = {
        "Most reacted": reaction_total * 8,
        "Most viewed": views,
        "Most forwarded": forwards * 5,
        "Most replied": replies * 12,
    }
    best = max(weighted.items(), key=lambda kv: kv[1])
    if best[1] <= 0:
        return "Most engaged"
    return best[0]


def build_week_top_comment(*, days: int = 7, db=None) -> Optional[Dict[str, Any]]:
    """Single most-engaged Telegram message in the window (views/reactions/replies).

    Side feature for the Summers desk — not call grading.
    """
    days = max(1, int(days or 7))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    database = db or get_db()
    try:
        with database._connect() as conn:
            rows = conn.execute(
                """SELECT m.id, m.author_id, m.author_name, m.author_username, m.content,
                          m.timestamp, m.created_at, m.source,
                          mm.views, mm.forwards, mm.replies, mm.reactions
                   FROM messages m
                   LEFT JOIN message_metrics mm ON mm.message_id = m.id
                   WHERE m.source = 'telegram'
                   ORDER BY m.id DESC
                   LIMIT 800"""
            ).fetchall()
    except Exception as exc:
        logger.warning("week top comment query failed: %s", exc)
        return None

    best: Optional[Dict[str, Any]] = None
    best_score = -1.0
    for row in rows:
        row = dict(row)
        ts = _parse_ts(row.get("timestamp")) or _parse_ts(row.get("created_at"))
        if ts is None or ts < cutoff:
            continue
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        try:
            views = int(row.get("views") or 0)
        except (TypeError, ValueError):
            views = 0
        try:
            forwards = int(row.get("forwards") or 0)
        except (TypeError, ValueError):
            forwards = 0
        try:
            replies = int(row.get("replies") or 0)
        except (TypeError, ValueError):
            replies = 0
        reaction_total = _reaction_total(row.get("reactions"))
        if views <= 0 and forwards <= 0 and replies <= 0 and reaction_total <= 0:
            continue
        score = float(views + forwards * 5 + reaction_total * 8 + replies * 12)
        if score < best_score:
            continue
        handle = str(row.get("author_username") or "").lstrip("@")
        display = f"@{handle}" if handle else str(row.get("author_name") or "Unknown")
        snippet = content if len(content) <= 220 else content[:217].rstrip() + "…"
        candidate = {
            "id": int(row["id"]),
            "author_name": row.get("author_name") or "Unknown",
            "author_username": row.get("author_username") or "",
            "display_name": display,
            "content": snippet,
            "views": views,
            "forwards": forwards,
            "replies": replies,
            "reaction_total": reaction_total,
            "top_reaction": _top_reaction(row.get("reactions")),
            "engagement_score": round(score, 1),
            "why": _engagement_why(views, forwards, reaction_total, replies),
            "days": days,
            "timestamp": row.get("timestamp") or row.get("created_at") or "",
        }
        if score > best_score or (
            score == best_score
            and (reaction_total, views, replies)
            > (
                int((best or {}).get("reaction_total") or 0),
                int((best or {}).get("views") or 0),
                int((best or {}).get("replies") or 0),
            )
        ):
            best = candidate
            best_score = score
    return best


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


def _proof_rows(db=None, *, days: Optional[int] = None, author_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load bounded public-proof fields only; classification happens in Python."""
    database = db or get_db()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    with database._connect() as conn:
        rows = conn.execute(
            """SELECT m.id, m.source, m.author_id, m.author_name, m.author_username,
                      m.content, m.timestamp, m.created_at, a.entities_json,
                      v.predicted_direction, v.conviction,
                      ps.tao_usd_price, ps.netuid, po.outcome, po.pump_pct_max,
                      po.price_1h, po.price_4h, po.price_24h
               FROM messages m
               LEFT JOIN message_analysis a ON a.message_id = m.id
               LEFT JOIN message_verdicts v ON v.message_id = m.id
               LEFT JOIN price_snapshots ps ON ps.message_id = m.id
               LEFT JOIN price_outcomes po ON po.message_id = m.id
               WHERE m.source = 'telegram' ORDER BY m.id DESC LIMIT 2000"""
        ).fetchall()
    out = []
    for raw in rows:
        row = dict(raw)
        timestamp = _parse_ts(row.get("timestamp")) or _parse_ts(row.get("created_at"))
        if cutoff and (timestamp is None or timestamp < cutoff):
            continue
        if author_id is not None and stable_author_id(row) != str(author_id):
            continue
        out.append(row)
    return out


def _conviction_rows(db=None) -> List[Dict[str, Any]]:
    """Load only the fields needed to audit current calls and past receipts."""
    database = db or get_db()
    with database._connect() as conn:
        rows = conn.execute(
            """SELECT m.id, m.source, m.author_id, m.author_name, m.author_username,
                      m.content, m.timestamp, m.created_at, a.entities_json,
                      v.verdict, v.predicted_direction, v.conviction,
                      ps.tao_usd_price, ps.netuid AS snap_netuid,
                      po.outcome, po.pump_pct_max, po.price_24h, po.price_24h_recorded_at
               FROM messages m
               LEFT JOIN message_analysis a ON a.message_id = m.id
               LEFT JOIN message_verdicts v ON v.message_id = m.id
               LEFT JOIN price_snapshots ps ON ps.message_id = m.id
               LEFT JOIN price_outcomes po ON po.message_id = m.id
               WHERE m.source = 'telegram'
               ORDER BY m.id DESC LIMIT 3000"""
        ).fetchall()
    return [dict(row) for row in rows]


def _conviction_methodology() -> Dict[str, Any]:
    return {
        "window_hours": CONVICTION_WINDOW_HOURS,
        "freshness_half_life_hours": CONVICTION_HALF_LIFE_HOURS,
        "minimum_calls": CONVICTION_MIN_CALLS,
        "minimum_contributors": CONVICTION_MIN_CONTRIBUTORS,
        "minimum_author_resolved_calls": CONVICTION_MIN_AUTHOR_SAMPLE,
        "minimum_call_conviction": CONVICTION_MIN_JURY_SCORE,
        "score_range": [-100, 100],
        "formula": (
            "Each current up/down call is weighted by jury conviction, "
            "a 24-hour freshness decay, and the caller's smoothed resolved-call accuracy. "
            "Only callers with at least 5 resolved qualifying calls contribute."
        ),
        "disclaimer": "Telegram consensus is evidence-qualified community commentary, not investment advice.",
    }


def _author_reliability_for_conviction(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Reliability uses resolved qualified receipts only, with beta smoothing."""
    stats: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        proof = classify_call(row)
        if not proof["resolved"] or proof["status"] not in ("hit", "miss"):
            continue
        aid = stable_author_id(row)
        item = stats.setdefault(aid, {"scored": 0, "hits": 0})
        item["scored"] += 1
        if proof["status"] == "hit":
            item["hits"] += 1
    for item in stats.values():
        # Beta(2,2) prior avoids treating a small perfect record as certainty.
        item["accuracy"] = (item["hits"] + 2.0) / (item["scored"] + 4.0)
        item["qualified"] = item["scored"] >= CONVICTION_MIN_AUTHOR_SAMPLE
    return stats


def _current_call_receipt(row: Dict[str, Any], direction: str, reliability: Dict[str, Any], age_hours: float, weight: float) -> Dict[str, Any]:
    return {
        "message_id": int(row["id"]),
        "author_id": stable_author_id(row),
        "author_name": row.get("author_name") or "Unknown",
        "author_username": row.get("author_username") or "",
        "content": str(row.get("content") or "")[:280],
        "timestamp": row.get("timestamp") or row.get("created_at"),
        "direction": direction,
        "jury_conviction": round(float(row.get("conviction") or 0.0), 1),
        "age_hours": round(age_hours, 1),
        "author_accuracy": round(float(reliability["accuracy"]) * 100.0, 1),
        "author_resolved_calls": int(reliability["scored"]),
        "weight": round(weight, 4),
    }


def build_subnet_telegram_conviction(
    *,
    netuid: Optional[int] = None,
    limit: int = 12,
    db=None,
    registry_names: Optional[Dict[int, str]] = None,
) -> Dict[str, Any]:
    """Evidence-weighted current Telegram direction per subnet.

    Resolved outcomes establish caller reliability; they never become current
    directional votes.  Current votes are explicit up/down calls in a rolling
    72-hour window from authors with enough independently resolved history.
    """
    now = datetime.now(timezone.utc)
    names = registry_names or {}
    methodology = _conviction_methodology()
    try:
        rows = _conviction_rows(db)
    except Exception as exc:
        logger.warning("subnet Telegram conviction query failed: %s", exc)
        return {"items": [], "count": 0, "empty": True, "methodology": methodology}

    reliability = _author_reliability_for_conviction(rows)
    buckets: Dict[int, Dict[str, Any]] = {}
    cutoff = now - timedelta(hours=CONVICTION_WINDOW_HOURS)
    for row in rows:
        timestamp = _parse_ts(row.get("timestamp")) or _parse_ts(row.get("created_at"))
        if timestamp is None or timestamp < cutoff:
            continue
        proof = classify_call(row)
        if proof.get("resolved") or not proof.get("eligible"):
            continue
        direction = resolve_direction(row.get("verdict"), row.get("predicted_direction"))
        try:
            jury_score = float(row.get("conviction") or 0.0)
        except (TypeError, ValueError):
            continue
        if direction not in ("up", "down") or jury_score < CONVICTION_MIN_JURY_SCORE:
            continue
        author = reliability.get(stable_author_id(row))
        if not author or not author["qualified"]:
            continue
        age_hours = max(0.0, (now - timestamp).total_seconds() / 3600.0)
        freshness = 0.5 ** (age_hours / CONVICTION_HALF_LIFE_HOURS)
        weight = (jury_score / 100.0) * freshness * float(author["accuracy"])
        for subnet_id in _netuids_from_row(row):
            if netuid is not None and int(subnet_id) != int(netuid):
                continue
            bucket = buckets.setdefault(
                int(subnet_id),
                {"signed_weight": 0.0, "total_weight": 0.0, "calls": [], "contributors": set()},
            )
            bucket["signed_weight"] += weight * (1.0 if direction == "up" else -1.0)
            bucket["total_weight"] += weight
            bucket["contributors"].add(stable_author_id(row))
            bucket["calls"].append(_current_call_receipt(row, direction, author, age_hours, weight))

    items: List[Dict[str, Any]] = []
    for subnet_id, bucket in buckets.items():
        calls = sorted(bucket["calls"], key=lambda call: call["timestamp"] or "", reverse=True)
        call_count, contributor_count = len(calls), len(bucket["contributors"])
        sufficient = call_count >= CONVICTION_MIN_CALLS and contributor_count >= CONVICTION_MIN_CONTRIBUTORS
        score = 0.0
        if bucket["total_weight"] > 0:
            score = max(-100.0, min(100.0, bucket["signed_weight"] / bucket["total_weight"] * 100.0))
        label = "mixed"
        if sufficient and score >= 20:
            label = "bullish"
        elif sufficient and score <= -20:
            label = "bearish"
        latest = calls[0]["timestamp"] if calls else None
        items.append(
            {
                "netuid": subnet_id,
                "name": names.get(subnet_id) or f"Subnet {subnet_id}",
                "ready": sufficient,
                "state": "ready" if sufficient else "insufficient_data",
                "label": label if sufficient else None,
                "score": round(score, 1) if sufficient else None,
                "call_count": call_count,
                "contributor_count": contributor_count,
                "latest_call_at": latest,
                "current_calls": calls[:6],
                "resolved_receipts": [],
                "insufficient_reason": None if sufficient else (
                    f"Needs {CONVICTION_MIN_CALLS} current calls from "
                    f"{CONVICTION_MIN_CONTRIBUTORS} evidence-qualified contributors."
                ),
            }
        )

    # Include honest empty-state rows for explicitly requested subnets and for
    # observed subnet mentions that cannot yet meet the evidence threshold.
    recent_subnets: Set[int] = set()
    for row in rows:
        timestamp = _parse_ts(row.get("timestamp")) or _parse_ts(row.get("created_at"))
        if timestamp is not None:
            recent_subnets.update(_netuids_from_row(row))
    if netuid is not None:
        recent_subnets.add(int(netuid))
    existing = {int(item["netuid"]) for item in items}
    for subnet_id in sorted(recent_subnets - existing):
        items.append(
            {
                "netuid": subnet_id,
                "name": names.get(subnet_id) or f"Subnet {subnet_id}",
                "ready": False,
                "state": "insufficient_data",
                "label": None,
                "score": None,
                "call_count": 0,
                "contributor_count": 0,
                "latest_call_at": None,
                "current_calls": [],
                "resolved_receipts": [],
                "insufficient_reason": (
                    f"Needs {CONVICTION_MIN_CALLS} current calls from "
                    f"{CONVICTION_MIN_CONTRIBUTORS} evidence-qualified contributors."
                ),
            }
        )

    # Add a small auditable receipt set per subnet, independently of current
    # freshness, so visitors can see why contributing callers are qualified.
    for item in items:
        contributors = {call["author_id"] for call in item["current_calls"]}
        receipts = []
        for row in rows:
            if item["netuid"] not in _netuids_from_row(row) or stable_author_id(row) not in contributors:
                continue
            proof = classify_call(row)
            if proof["resolved"]:
                receipts.append(_receipt(row, proof))
            if len(receipts) >= 6:
                break
        item["resolved_receipts"] = receipts

    items.sort(key=lambda item: (item["ready"], abs(item["score"] or 0), item["call_count"]), reverse=True)
    return {
        "items": items[:max(1, int(limit))],
        "count": len(items),
        "empty": not items,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "methodology": methodology,
    }


def _divergence_methodology() -> Dict[str, Any]:
    return {
        "horizon": "24h",
        "default_window_days": DIVERGENCE_DEFAULT_DAYS,
        "maximum_window_days": DIVERGENCE_MAX_DAYS,
        "minimum_calls": DIVERGENCE_MIN_CALLS,
        "minimum_contributors": DIVERGENCE_MIN_CONTRIBUTORS,
        "minimum_call_conviction": CONVICTION_MIN_JURY_SCORE,
        "formula": (
            "Telegram-only calls are grouped by subnet and their message timestamps. "
            "Only qualifying calls with recorded 24h outcomes count; each call is "
            "weighted by its jury conviction. Outcomes describe observed movement "
            "after those calls and do not establish causality."
        ),
        "disclaimer": (
            "This compares recorded Telegram calls with later recorded price outcomes; "
            "it does not claim Telegram caused or predicted the move. Not financial advice."
        ),
    }


def _outcome_direction(proof: Dict[str, Any]) -> Optional[str]:
    outcome = str(proof.get("raw_outcome") or "").lower()
    if outcome in ("pump", "mild_pump"):
        return "up"
    if outcome in ("dump", "mild_dump"):
        return "down"
    if outcome == "stable":
        return "flat"
    return None


def _story_label(consensus_direction: Optional[str], observed_direction: Optional[str]) -> tuple[str, str]:
    """Return a factual label and state, never a causal or predictive claim."""
    if observed_direction == "flat":
        return "outcome-neutral", "neutral_outcome"
    if consensus_direction == observed_direction and consensus_direction in ("up", "down"):
        return "consensus-confirmed", "aligned"
    if consensus_direction in ("up", "down") and observed_direction in ("up", "down"):
        return "loud-but-wrong", "diverged"
    return "mixed-evidence", "mixed"


def _divergence_receipt(row: Dict[str, Any], proof: Dict[str, Any]) -> Dict[str, Any]:
    receipt = _receipt(row, proof)
    receipt.update(
        {
            "direction": proof["direction"],
            "outcome_direction": _outcome_direction(proof),
            "jury_conviction": round(float(row.get("conviction") or 0.0), 1),
        }
    )
    return receipt


def _has_24h_observation(row: Dict[str, Any], message_timestamp: datetime) -> bool:
    """Require a positive 24h price, a 24h-mature message, and an audit timestamp."""
    try:
        recorded_at = _parse_ts(row.get("price_24h_recorded_at"))
        return (
            row.get("price_24h") is not None
            and float(row["price_24h"]) > 0
            and recorded_at is not None
            and recorded_at >= message_timestamp + timedelta(hours=24)
        )
    except (TypeError, ValueError):
        return False


def build_telegram_divergence_stories(
    *,
    netuid: Optional[int] = None,
    days: int = DIVERGENCE_DEFAULT_DAYS,
    limit: int = 8,
    db=None,
    registry_names: Optional[Dict[int, str]] = None,
) -> Dict[str, Any]:
    """Build bounded per-subnet Telegram-consensus versus observed-outcome stories.

    A story is eligible only when at least two different Telegram contributors
    made qualifying calls that have resolved outcomes inside the requested
    window.  This derives historical evidence from immutable message/snapshot/
    outcome receipts, avoiding a second mutable interpretation store.
    """
    now = datetime.now(timezone.utc)
    names = registry_names or {}
    methodology = _divergence_methodology()
    days = max(1, min(DIVERGENCE_MAX_DAYS, int(days or DIVERGENCE_DEFAULT_DAYS)))
    cutoff = now - timedelta(days=days)
    try:
        rows = _conviction_rows(db)
    except Exception as exc:
        logger.warning("Telegram divergence query failed: %s", exc)
        return {
            "stories": [], "count": 0, "empty": True, "days": days,
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "methodology": methodology,
        }

    buckets: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        timestamp = _parse_ts(row.get("timestamp")) or _parse_ts(row.get("created_at"))
        if timestamp is None or timestamp < cutoff:
            continue
        proof = classify_call(row)
        if not proof["eligible"]:
            continue
        for subnet_id in _netuids_from_row(row):
            subnet_id = int(subnet_id)
            if netuid is not None and subnet_id != int(netuid):
                continue
            bucket = buckets.setdefault(subnet_id, {"receipts": [], "pending": 0})
            if proof["resolved"] and _has_24h_observation(row, timestamp):
                bucket["receipts"].append((row, proof, timestamp))
            else:
                bucket["pending"] += 1

    stories: List[Dict[str, Any]] = []
    for subnet_id, bucket in buckets.items():
        resolved = bucket["receipts"]
        contributors = {stable_author_id(row) for row, _proof, _ts in resolved}
        receipts = [
            _divergence_receipt(row, proof)
            for row, proof, _ts in sorted(resolved, key=lambda item: item[2], reverse=True)
        ]
        call_count = len(receipts)
        contributor_count = len(contributors)
        sufficient = call_count >= DIVERGENCE_MIN_CALLS and contributor_count >= DIVERGENCE_MIN_CONTRIBUTORS
        base: Dict[str, Any] = {
            "netuid": subnet_id,
            "name": names.get(subnet_id) or f"Subnet {subnet_id}",
            "ready": sufficient,
            "state": "insufficient_data",
            "label": None,
            "headline": None,
            "time_window": {
                "start": min((ts for _row, _proof, ts in resolved), default=None),
                "end": max((ts for _row, _proof, ts in resolved), default=None),
                "horizon": "24h",
                "days": days,
            },
            "consensus_direction": None,
            "consensus_score": None,
            "observed_direction": None,
            "observed_move_pct": None,
            "observed_outcome": None,
            "qualifying_call_count": call_count,
            "contributor_count": contributor_count,
            "pending_qualifying_call_count": int(bucket["pending"]),
            "receipts": receipts[:12],
            "insufficient_reason": (
                f"Needs {DIVERGENCE_MIN_CALLS} resolved qualifying calls from "
                f"{DIVERGENCE_MIN_CONTRIBUTORS} Telegram contributors."
            ),
            "caveat": "Outcomes are observed after each receipt's recorded price snapshot; no causal claim is made.",
        }
        if not sufficient:
            stories.append(base)
            continue

        signed_weight = total_weight = 0.0
        outcome_weights: Dict[str, float] = {"up": 0.0, "down": 0.0, "flat": 0.0}
        moves: List[float] = []
        outcome_names: Dict[str, int] = defaultdict(int)
        for row, proof, _ts in resolved:
            weight = max(0.0, float(row.get("conviction") or 0.0))
            direction = proof["direction"]
            if direction == "up":
                signed_weight += weight
                total_weight += weight
            elif direction == "down":
                signed_weight -= weight
                total_weight += weight
            observed = _outcome_direction(proof)
            if observed:
                outcome_weights[observed] += weight
            if proof.get("move_pct") is not None:
                moves.append(float(proof["move_pct"]))
            if proof.get("raw_outcome"):
                outcome_names[str(proof["raw_outcome"])] += 1

        score = (signed_weight / total_weight * 100.0) if total_weight else 0.0
        consensus_direction = "up" if score >= 20 else ("down" if score <= -20 else None)
        observed_direction = max(outcome_weights, key=outcome_weights.get) if any(outcome_weights.values()) else None
        label, state = _story_label(consensus_direction, observed_direction)
        base.update(
            {
                "ready": True,
                "state": state,
                "label": label,
                "headline": (
                    f"Telegram consensus {consensus_direction or 'mixed'}; "
                    f"recorded 24h outcome {observed_direction or 'unavailable'}."
                ),
                "consensus_direction": consensus_direction or "mixed",
                "consensus_score": round(score, 1),
                "observed_direction": observed_direction,
                "observed_move_pct": round(sum(moves) / len(moves), 2) if moves else None,
                "observed_outcome": max(outcome_names, key=outcome_names.get) if outcome_names else None,
                "insufficient_reason": None,
            }
        )
        stories.append(base)

    stories.sort(
        key=lambda item: (
            item["ready"], item["time_window"]["end"] or datetime.min.replace(tzinfo=timezone.utc),
            item["qualifying_call_count"],
        ),
        reverse=True,
    )
    return {
        "stories": stories[:max(1, min(50, int(limit)))],
        "count": len(stories),
        "empty": not stories,
        "days": days,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "methodology": methodology,
    }


def proof_for_message(row: Dict[str, Any]) -> Dict[str, Any]:
    """Compact card-safe proof object; no internal database fields."""
    proof = classify_call(row)
    return {
        "eligible": proof["eligible"],
        "status": proof["status"],
        "evaluation": proof["evaluation"],
        "direction": proof["direction"],
        "move_pct": proof["move_pct"],
        "price_basis": proof.get("price_basis"),
        "outcome": proof["raw_outcome"],
        "threshold": proof["threshold"],
    }


def build_telegram_proof_band(*, db=None) -> Dict[str, Any]:
    """Backward-compatible aggregate from the shared public-proof contract."""
    graded = hits = misses = neutral = pending = ungradeable = 0
    recent: List[Dict[str, Any]] = []
    try:
        rows = _proof_rows(db)
    except Exception:
        return {
            "graded": 0, "hits": 0, "misses": 0, "neutral": 0,
            "pending": 0, "ungradeable": 0, "hit_rate": None, "ready": False, "recent": [],
        }

    for row in rows:
        proof = classify_call(row)
        if not proof["resolved"]:
            if proof["status"] == "pending":
                pending += 1
            else:
                ungradeable += 1
            continue
        graded += 1
        if proof["status"] == "hit":
            hits += 1
        elif proof["status"] == "miss":
            misses += 1
        else:
            neutral += 1
        if len(recent) < 4:
            recent.append(
                {
                    "id": int(row["id"]), "author_name": row.get("author_name"),
                    "netuid": row.get("netuid"), "move_pct": proof["move_pct"],
                    "pump_pct_max": proof["move_pct"], "status": proof["status"],
                    "hit": proof["status"] == "hit",
                }
            )

    scored = hits + misses
    hit_rate = round((hits / scored) * 100.0, 1) if scored else None
    return {
        "graded": graded, "hits": hits, "misses": misses, "neutral": neutral,
        "pending": pending, "ungradeable": ungradeable,
        "hit_rate": hit_rate, "ready": scored >= MIN_LEADERBOARD_SAMPLE, "recent": recent,
    }


def build_telegram_caller_leaderboard(*, days: int = 30, limit: int = 25, db=None) -> Dict[str, Any]:
    """Evidence-only caller table for the selected rolling window."""
    rows = _proof_rows(db, days=days)
    callers: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        proof = classify_call(row)
        if not proof["resolved"]:
            continue
        aid = stable_author_id(row)
        entry = callers.setdefault(aid, {
            "author_id": aid, "author_name": row.get("author_name") or "Unknown",
            "author_username": row.get("author_username") or "", "hits": 0,
            "misses": 0, "neutral": 0, "sample_size": 0, "recent": [],
        })
        entry["sample_size"] += 1
        _status_counter = {"hit": "hits", "miss": "misses", "neutral": "neutral"}
        entry[_status_counter.get(proof["status"], "neutral")] += 1
        if len(entry["recent"]) < 3:
            entry["recent"].append(_receipt(row, proof))
    results = []
    for item in callers.values():
        scored = item["hits"] + item["misses"]
        item["accuracy"] = round(item["hits"] / scored * 100.0, 1) if scored else None
        item["qualified"] = item["sample_size"] >= MIN_LEADERBOARD_SAMPLE and scored > 0
        item["minimum_sample"] = MIN_LEADERBOARD_SAMPLE
        results.append(item)
    results.sort(key=lambda item: (item["qualified"], item["accuracy"] or -1, item["sample_size"]), reverse=True)
    return {
        "days": days, "minimum_sample": MIN_LEADERBOARD_SAMPLE, "count": len(results),
        "callers": results[:limit], "empty": not results,
        "disclaimer": "Prediction accuracy is measured from resolved qualifying calls only, not engagement. Not financial advice.",
    }


def _receipt(row: Dict[str, Any], proof: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "message_id": int(row["id"]), "content": str(row.get("content") or "")[:280],
        "timestamp": row.get("timestamp") or row.get("created_at"), "netuid": row.get("netuid"),
        "proof": proof_for_message(row),
    }


def list_telegram_caller_receipts(*, author_id: str, days: int = 30, limit: int = 20, offset: int = 0, db=None) -> Dict[str, Any]:
    """Paginated public receipts, restricted to resolved qualifying evidence."""
    receipts = []
    for row in _proof_rows(db, days=days, author_id=author_id):
        proof = classify_call(row)
        if proof["resolved"]:
            receipts.append(_receipt(row, proof))
    page = receipts[offset: offset + limit]
    return {"author_id": author_id, "days": days, "count": len(page), "total": len(receipts),
            "receipts": page, "empty": not receipts, "offset": offset, "limit": limit}


_MIN_24H_SUMMARY_MESSAGES = 10


def _mention_context(rows: List[str]) -> Optional[str]:
    """Return one concise public-message line explaining a subnet's mentions."""
    snippets: List[str] = []
    for raw in rows[:2]:
        text = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not text:
            continue
        if len(text) > 110:
            text = text[:107].rstrip() + "…"
        if text not in snippets:
            snippets.append(text)
    return " / ".join(snippets) if snippets else None


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
    mention_contexts: Dict[int, List[str]] = defaultdict(list)

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
                if row.get("content") and len(mention_contexts[netuid]) < 2:
                    mention_contexts[netuid].append(str(row["content"]))

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
                "mention_context": _mention_context(mention_contexts.get(netuid) or []),
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
