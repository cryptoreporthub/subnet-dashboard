"""Message-intel store reset — ponytail check for cutoff deletes."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from internal.message_intel.reset_store import (
    cutoff_since_yesterday,
    delete_messages_before,
    wipe_message_intel_db,
)
from message_intel.models import Database


def _insert_message(db: Database, ts: datetime, content: str = "SN1 chatter") -> int:
    iso = ts.astimezone(timezone.utc).isoformat()
    with db._connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO messages (source, group_id, group_name, content, timestamp)
            VALUES ('telegram', '1', 'OfficialSubnetSummer', ?, ?)
            """,
            (content, iso),
        )
        mid = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO message_metrics (message_id, views) VALUES (?, 10)",
            (mid,),
        )
        conn.execute(
            """
            INSERT INTO message_analysis (message_id, entities_json)
            VALUES (?, '{"subnets":["SN1"]}')
            """,
            (mid,),
        )
        conn.commit()
    return mid


def test_delete_messages_before_keeps_recent(tmp_path):
    path = str(tmp_path / "message_intel.db")
    db = Database(path)
    old = datetime.now(timezone.utc) - timedelta(days=10)
    recent = datetime.now(timezone.utc) - timedelta(hours=2)
    _insert_message(db, old, "old")
    _insert_message(db, recent, "fresh")

    out = delete_messages_before(cutoff_since_yesterday(), db_path=path)
    assert out["ok"]
    assert out["deleted"]["messages"] == 1

    with db._connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    assert n == 1


def test_wipe_message_intel_db(tmp_path):
    path = str(tmp_path / "message_intel.db")
    db = Database(path)
    _insert_message(db, datetime.now(timezone.utc), "x")
    out = wipe_message_intel_db(path)
    assert out["ok"]
    with sqlite3.connect(path) as conn:
        n = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    assert n == 0
