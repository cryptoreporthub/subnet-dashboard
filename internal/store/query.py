"""Query layer for durable SQLite store (Phase F shared contract)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.store.db import STORE_DB_PATH, connect, create_tables

MAX_TRAIL_ROWS = 500


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def _json_loads(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _row_to_record(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "decision_type": row["decision_type"],
        "decision": _json_loads(row["decision_json"], {}),
        "signals": _json_loads(row["signals_json"], []),
        "subnet": row["subnet"],
        "netuid": row["netuid"],
    }


def record_trace_row(record: Dict[str, Any], *, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Insert one trace row into SQLite (idempotent on duplicate id)."""
    conn = connect(db_path)
    try:
        create_tables(conn)
        conn.execute(
            """
            INSERT OR REPLACE INTO trail_rows
                (id, created_at, decision_type, decision_json, signals_json, subnet, netuid)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(record.get("id") or f"tr_{_utcnow_z()}"),
                str(record.get("created_at") or _utcnow_z()),
                str(record.get("decision_type") or "decision"),
                _json_dumps(record.get("decision") or {}),
                _json_dumps(record.get("signals") or []),
                record.get("subnet"),
                record.get("netuid"),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return record


def get_trail_row(trace_id: str, *, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = connect(db_path)
    try:
        create_tables(conn)
        row = conn.execute(
            """
            SELECT id, created_at, decision_type, decision_json, signals_json, subnet, netuid
            FROM trail_rows WHERE id = ?
            """,
            (trace_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_record(row)
    finally:
        conn.close()


def get_trail_rows(
    limit: int = 100,
    signal: Optional[str] = None,
    *,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return newest trail rows first; optional signal type filter."""
    conn = connect(db_path)
    try:
        create_tables(conn)
        params: List[Any] = []
        where = ""
        if signal:
            where = "WHERE signals_json LIKE ?"
            params.append(f"%{signal}%")
        params.append(max(1, int(limit)))
        rows = conn.execute(
            f"""
            SELECT id, created_at, decision_type, decision_json, signals_json, subnet, netuid
            FROM trail_rows
            {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [_row_to_record(row) for row in rows]
    finally:
        conn.close()


def get_dispositions(*, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = connect(db_path)
    try:
        create_tables(conn)
        rows = conn.execute(
            "SELECT netuid, action, score, updated_at FROM dispositions ORDER BY netuid"
        ).fetchall()
        return [
            {
                "netuid": row["netuid"],
                "action": row["action"],
                "score": row["score"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_decision_lineage(
    limit: int = 100,
    *,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    conn = connect(db_path)
    try:
        create_tables(conn)
        rows = conn.execute(
            """
            SELECT id, created_at, total_records, top_signal_types_json, last_record_json
            FROM decision_lineage
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "total_records": row["total_records"],
                    "top_signal_types": _json_loads(row["top_signal_types_json"], []),
                    "last_record": _json_loads(row["last_record_json"], {}),
                }
            )
        return out
    finally:
        conn.close()


def count_trail(*, db_path: Optional[str] = None) -> int:
    conn = connect(db_path)
    try:
        create_tables(conn)
        row = conn.execute("SELECT COUNT(*) AS c FROM trail_rows").fetchone()
        return int(row["c"] if row else 0)
    finally:
        conn.close()


def count_dispositions(*, db_path: Optional[str] = None) -> int:
    conn = connect(db_path)
    try:
        create_tables(conn)
        row = conn.execute("SELECT COUNT(*) AS c FROM dispositions").fetchone()
        return int(row["c"] if row else 0)
    finally:
        conn.close()


def count_decision_lineage(*, db_path: Optional[str] = None) -> int:
    conn = connect(db_path)
    try:
        create_tables(conn)
        row = conn.execute("SELECT COUNT(*) AS c FROM decision_lineage").fetchone()
        return int(row["c"] if row else 0)
    finally:
        conn.close()


def get_store_stats(*, db_path: Optional[str] = None) -> Dict[str, Any]:
    return {
        "trail_count": count_trail(db_path=db_path),
        "disposition_count": count_dispositions(db_path=db_path),
        "lineage_count": count_decision_lineage(db_path=db_path),
        "db_path": db_path or STORE_DB_PATH,
    }


def upsert_trail_row(record: Dict[str, Any], *, db_path: Optional[str] = None) -> None:
    """Idempotent insert — skip if id already present."""
    conn = connect(db_path)
    try:
        create_tables(conn)
        row_id = str(record.get("id") or "")
        if not row_id:
            return
        existing = conn.execute("SELECT 1 FROM trail_rows WHERE id = ?", (row_id,)).fetchone()
        if existing:
            return
        conn.execute(
            """
            INSERT INTO trail_rows
                (id, created_at, decision_type, decision_json, signals_json, subnet, netuid)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                str(record.get("created_at") or _utcnow_z()),
                str(record.get("decision_type") or "decision"),
                _json_dumps(record.get("decision") or {}),
                _json_dumps(record.get("signals") or []),
                record.get("subnet"),
                record.get("netuid"),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_disposition(
    netuid: int,
    action: str,
    score: Optional[float],
    updated_at: Optional[str],
    *,
    db_path: Optional[str] = None,
) -> None:
    conn = connect(db_path)
    try:
        create_tables(conn)
        conn.execute(
            """
            INSERT INTO dispositions (netuid, action, score, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(netuid) DO UPDATE SET
                action = excluded.action,
                score = excluded.score,
                updated_at = excluded.updated_at
            """,
            (int(netuid), str(action), score, updated_at or _utcnow_z()),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_decision_lineage_row(
    row_id: str,
    created_at: str,
    total_records: int,
    top_signal_types: Any,
    last_record: Any,
    *,
    db_path: Optional[str] = None,
) -> None:
    conn = connect(db_path)
    try:
        create_tables(conn)
        existing = conn.execute("SELECT 1 FROM decision_lineage WHERE id = ?", (row_id,)).fetchone()
        if existing:
            return
        conn.execute(
            """
            INSERT INTO decision_lineage
                (id, created_at, total_records, top_signal_types_json, last_record_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                row_id,
                created_at,
                int(total_records),
                _json_dumps(top_signal_types),
                _json_dumps(last_record),
            ),
        )
        conn.commit()
    finally:
        conn.close()
