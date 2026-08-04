"""Reset message-intel SQLite store (Telegram desk history)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from internal.message_intel.store import reset_db_cache


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def cutoff_since_yesterday() -> datetime:
    """UTC midnight at the start of yesterday — keep yesterday + today."""
    today = _utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=1)


def cutoff_keep_days(days: int) -> datetime:
    days = max(1, int(days))
    return _utc_now() - timedelta(days=days)


def _message_ids_before(conn, cutoff_iso: str) -> List[int]:
    rows = conn.execute(
        """
        SELECT id FROM messages
        WHERE COALESCE(timestamp, created_at) < ?
        """,
        (cutoff_iso,),
    ).fetchall()
    return [int(r[0]) for r in rows]


def _delete_message_ids(conn, ids: List[int]) -> Dict[str, int]:
    if not ids:
        return {"messages": 0}
    placeholders = ",".join("?" * len(ids))
    counts: Dict[str, int] = {}
    for table in (
        "price_outcomes",
        "price_snapshots",
        "message_verdicts",
        "message_analysis",
        "message_metrics",
    ):
        cur = conn.execute(
            f"DELETE FROM {table} WHERE message_id IN ({placeholders})",
            ids,
        )
        counts[table] = cur.rowcount
    cur = conn.execute(
        f"DELETE FROM messages WHERE id IN ({placeholders})",
        ids,
    )
    counts["messages"] = cur.rowcount
    return counts


def delete_messages_before(
    cutoff: datetime,
    db_path: Optional[str] = None,
    dry_run: bool = False,
    wipe_aggregates: bool = False,
) -> Dict[str, Any]:
    """Delete messages (and children) strictly before cutoff UTC."""
    from message_intel.models import Database

    path = db_path or os.environ.get("MESSAGE_INTEL_DB", "data/message_intel.db")
    cutoff = cutoff.astimezone(timezone.utc)
    cutoff_iso = cutoff.isoformat()

    if not os.path.isfile(path):
        return {
            "ok": True,
            "mode": "before_cutoff",
            "cutoff": cutoff_iso,
            "dry_run": dry_run,
            "deleted": {},
            "remaining_messages": 0,
        }

    db = Database(path)
    with db._connect() as conn:
        ids = _message_ids_before(conn, cutoff_iso)
        remaining_before = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        if dry_run:
            return {
                "ok": True,
                "mode": "before_cutoff",
                "cutoff": cutoff_iso,
                "dry_run": True,
                "would_delete_messages": len(ids),
                "remaining_messages": remaining_before - len(ids),
            }
        deleted = _delete_message_ids(conn, ids)
        if wipe_aggregates:
            deleted["author_reliability"] = conn.execute(
                "DELETE FROM author_reliability"
            ).rowcount
            deleted["pattern_correlations"] = conn.execute(
                "DELETE FROM pattern_correlations"
            ).rowcount
        remaining = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        conn.commit()

    reset_db_cache()
    return {
        "ok": True,
        "mode": "before_cutoff",
        "cutoff": cutoff_iso,
        "dry_run": False,
        "deleted": deleted,
        "remaining_messages": remaining,
    }


def wipe_message_intel_db(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Remove the DB file (+ WAL) and recreate empty schema."""
    path = db_path or os.environ.get("MESSAGE_INTEL_DB", "data/message_intel.db")
    removed: List[str] = []
    for suffix in ("", "-wal", "-shm"):
        p = f"{path}{suffix}" if suffix else path
        if os.path.isfile(p):
            os.remove(p)
            removed.append(p)

    from message_intel.models import Database

    Database(path)
    reset_db_cache()
    return {"ok": True, "mode": "full", "removed_files": removed}


def clean_social_intel_alerts() -> Dict[str, Any]:
    """Drop social_intel rows from alerts.json (desk-adjacent noise after reset)."""
    from internal.signals.alerts import AlertEngine

    engine = AlertEngine()
    data = engine.load_alerts()
    alerts = data.get("alerts") if isinstance(data.get("alerts"), list) else []
    kept = [a for a in alerts if str(a.get("alert_type") or "") != "social_intel"]
    removed = len(alerts) - len(kept)
    if removed:
        data["alerts"] = kept
        data["updated_at"] = _utc_now().isoformat().replace("+00:00", "Z")
        with open(engine.alerts_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
    return {"ok": True, "social_intel_alerts_removed": removed}


def reset_message_intel(
    mode: str = "yesterday",
    keep_days: int = 7,
    dry_run: bool = False,
    clean_alerts: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    mode:
      yesterday — keep from start of yesterday UTC (week panels may be quiet)
      week — keep last N days (preserves comment-of-week / champions / crowns)
      full — wipe entire message_intel.db
    """
    summary: Dict[str, Any] = {"mode": mode}
    if mode == "full":
        if dry_run:
            path = db_path or os.environ.get("MESSAGE_INTEL_DB", "data/message_intel.db")
            exists = os.path.isfile(path)
            summary.update(
                {
                    "ok": True,
                    "dry_run": True,
                    "would_wipe_db": exists,
                    "db_path": path,
                }
            )
        else:
            summary.update(wipe_message_intel_db(db_path))
    elif mode == "week":
        summary.update(
            delete_messages_before(
                cutoff_keep_days(keep_days),
                db_path=db_path,
                dry_run=dry_run,
                wipe_aggregates=not dry_run,
            )
        )
    else:
        summary.update(
            delete_messages_before(
                cutoff_since_yesterday(),
                db_path=db_path,
                dry_run=dry_run,
                wipe_aggregates=not dry_run,
            )
        )

    if clean_alerts and not dry_run:
        summary["alerts"] = clean_social_intel_alerts()
    return summary
