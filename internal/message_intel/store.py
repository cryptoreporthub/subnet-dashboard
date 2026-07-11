"""Persistence accessors for the message-intel SQLite store."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict, List, Optional

from message_intel.models import Database

DB_PATH = os.environ.get("MESSAGE_INTEL_DB", "data/message_intel.db")


@lru_cache(maxsize=1)
def get_db(db_path: Optional[str] = None) -> Database:
    return Database(db_path=db_path or DB_PATH)


def reset_db_cache() -> None:
    get_db.cache_clear()


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
    except Exception as exc:
        return {"ok": False, "error": str(exc), "total_messages": 0}

    channels: List[Dict[str, Any]] = []
    for row in by_source:
        channels.append({"source": row["source"], "count": int(row["n"])})

    return {
        "ok": True,
        "total_messages": int(total),
        "high_conviction_count": int(high_conv or 0),
        "channels": channels,
        "recent": [dict(r) for r in recent],
    }
