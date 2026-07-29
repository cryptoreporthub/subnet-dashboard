"""Persistence accessors for the message-intel SQLite store."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional

from message_intel.models import Database

DB_PATH = os.environ.get("MESSAGE_INTEL_DB", "data/message_intel.db")


def _resolve_db_path(db_path: Optional[str] = None) -> str:
    return db_path or os.environ.get("MESSAGE_INTEL_DB", DB_PATH)


@lru_cache(maxsize=1)
def get_db(db_path: Optional[str] = None) -> Database:
    return Database(db_path=_resolve_db_path(db_path))


def reset_db_cache() -> None:
    get_db.cache_clear()


def last_telegram_external_id(db: Optional[Database] = None) -> Optional[int]:
    """Highest Telegram message_id we have ingested (for gap-aware backfill)."""
    database = db or get_db()
    try:
        with database._connect() as conn:
            row = conn.execute(
                """SELECT external_message_id FROM messages
                   WHERE source = 'telegram' AND external_message_id IS NOT NULL
                   ORDER BY CAST(external_message_id AS INTEGER) DESC LIMIT 1"""
            ).fetchone()
        if not row or not row["external_message_id"]:
            return None
        return int(row["external_message_id"])
    except (TypeError, ValueError, Exception):
        return None


def last_telegram_group_id(db: Optional[Database] = None) -> Optional[int]:
    """Most recent Telegram group_id in the store — entity fallback when username lookup fails."""
    database = db or get_db()
    try:
        with database._connect() as conn:
            row = conn.execute(
                """SELECT group_id FROM messages
                   WHERE source = 'telegram' AND group_id IS NOT NULL AND group_id != ''
                   ORDER BY id DESC LIMIT 1"""
            ).fetchone()
        if not row or not row["group_id"]:
            return None
        return int(str(row["group_id"]).strip())
    except (TypeError, ValueError, Exception):
        return None


def live_stats(db: Optional[Database] = None) -> Dict[str, Any]:
    """Aggregate counts from the SQLite store for summaries and health."""
    database = db or get_db()
    try:
        with database._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            by_source = conn.execute(
                "SELECT source, COUNT(*) AS n FROM messages GROUP BY source ORDER BY n DESC"
            ).fetchall()
            high_conv = conn.execute(
                """SELECT COUNT(*) FROM message_verdicts WHERE conviction >= ?""",
                (60.0,),
            ).fetchone()[0]
            recent = conn.execute(
                """SELECT m.source, m.group_name, m.author_name, m.timestamp, v.conviction, v.verdict
                   FROM messages m
                   LEFT JOIN message_verdicts v ON v.message_id = m.id
                   ORDER BY m.id DESC LIMIT 5"""
            ).fetchall()
            last_row = conn.execute(
                "SELECT timestamp FROM messages ORDER BY id DESC LIMIT 1"
            ).fetchone()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "total_messages": 0}

    channels: List[Dict[str, Any]] = []
    for row in by_source:
        channels.append({"source": row["source"], "count": int(row["n"])})

    last_message_at: Optional[str] = None
    last_message_age_seconds: Optional[float] = None
    if last_row and last_row["timestamp"]:
        last_message_at = str(last_row["timestamp"])
        try:
            from internal.message_intel.rollup import _parse_ts

            ts = _parse_ts(last_message_at)
            if ts is not None:
                last_message_age_seconds = (
                    datetime.now(timezone.utc) - ts.astimezone(timezone.utc)
                ).total_seconds()
        except Exception:
            pass

    out: Dict[str, Any] = {
        "ok": True,
        "total_messages": int(total),
        "high_conviction_count": int(high_conv or 0),
        "channels": channels,
        "recent": [dict(r) for r in recent],
    }
    if last_message_at:
        out["last_message_at"] = last_message_at
    if last_message_age_seconds is not None:
        out["last_message_age_seconds"] = round(last_message_age_seconds, 1)
    return out
