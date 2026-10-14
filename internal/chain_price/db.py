"""SQLite persistence for forward chain price samples."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from internal.chain_price.config import (
    CHAIN_PRICE_DB_PATH,
    RETENTION_DAYS,
    RETENTION_FULL_DAYS,
    ROW_CAP,
)
from internal.store.db import db_conn, ensure_db_dir

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chain_blocks (
    provider TEXT NOT NULL,
    block INTEGER NOT NULL,
    block_hash TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,
    bucket_ts INTEGER NOT NULL,
    kind TEXT NOT NULL,
    n_subnets INTEGER NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (provider, block)
);

CREATE TABLE IF NOT EXISTS chain_price_samples (
    netuid INTEGER NOT NULL,
    block INTEGER NOT NULL,
    provider TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,
    registered_at INTEGER NOT NULL,
    tao_reserve_raw INTEGER NOT NULL,
    alpha_reserve_raw INTEGER NOT NULL,
    price_tao REAL NOT NULL,
    spot_price_tao REAL,
    unit TEXT NOT NULL DEFAULT 'tao',
    quality TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    block_hash TEXT,
    series_key TEXT,
    PRIMARY KEY (netuid, block, provider)
);

CREATE INDEX IF NOT EXISTS idx_chain_price_samples_block ON chain_price_samples(block);
CREATE INDEX IF NOT EXISTS idx_chain_price_samples_ts ON chain_price_samples(ts_ms);
CREATE INDEX IF NOT EXISTS idx_chain_price_samples_series_ts
    ON chain_price_samples(series_key, ts_ms);
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _migrate_columns(conn) -> None:
    cur = conn.execute("PRAGMA table_info(chain_price_samples)")
    cols = {row[1] for row in cur.fetchall()}
    if "block_hash" not in cols:
        conn.execute("ALTER TABLE chain_price_samples ADD COLUMN block_hash TEXT")
    if "series_key" not in cols:
        conn.execute("ALTER TABLE chain_price_samples ADD COLUMN series_key TEXT")


def ensure_schema(path: Optional[str] = None) -> str:
    db_path = ensure_db_dir(path or CHAIN_PRICE_DB_PATH)
    with db_conn(db_path) as conn:
        conn.executescript(_SCHEMA_SQL)
        _migrate_columns(conn)
        conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        conn.commit()
    return db_path


def insert_block_row(
    *,
    provider: str,
    block: int,
    block_hash: str,
    ts_ms: int,
    bucket_ts: int,
    kind: str,
    n_subnets: int,
    path: Optional[str] = None,
) -> None:
    with db_conn(path or CHAIN_PRICE_DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO chain_blocks
            (provider, block, block_hash, ts_ms, bucket_ts, kind, n_subnets, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (provider, block, block_hash, ts_ms, bucket_ts, kind, n_subnets, _utc_now_iso()),
        )
        conn.commit()


def insert_sample_rows(rows: Iterable[Dict[str, Any]], path: Optional[str] = None) -> int:
    payload = list(rows)
    if not payload:
        return 0
    with db_conn(path or CHAIN_PRICE_DB_PATH) as conn:
        before = conn.total_changes
        conn.executemany(
            """
            INSERT OR IGNORE INTO chain_price_samples
            (netuid, block, provider, ts_ms, registered_at, tao_reserve_raw, alpha_reserve_raw,
             price_tao, spot_price_tao, unit, quality, schema_version, block_hash, series_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r["netuid"],
                    r["block"],
                    r["provider"],
                    r["ts_ms"],
                    r["registered_at"],
                    r["tao_reserve_raw"],
                    r["alpha_reserve_raw"],
                    r["price_tao"],
                    r.get("spot_price_tao"),
                    r.get("unit", "tao"),
                    r["quality"],
                    r["schema_version"],
                    r.get("block_hash"),
                    r.get("series_key"),
                )
                for r in payload
            ],
        )
        conn.commit()
        return conn.total_changes - before


def select_chain_bar(
    *,
    netuid: int,
    registered_at: int,
    series_key: str,
    resolve_at_ms: int,
    max_staleness_ms: int,
    path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    db_path = path or CHAIN_PRICE_DB_PATH
    earliest = resolve_at_ms - max_staleness_ms
    half = max_staleness_ms // 2
    with db_conn(db_path) as conn:
        cur = conn.execute(
            """
            SELECT netuid, block, provider, ts_ms, registered_at, price_tao, unit, quality,
                   schema_version, block_hash, series_key
            FROM chain_price_samples
            WHERE series_key = ? AND registered_at = ? AND quality != 'disputed'
              AND ts_ms <= ? AND ts_ms >= ?
            ORDER BY ts_ms DESC
            LIMIT 1
            """,
            (series_key, registered_at, resolve_at_ms, earliest),
        )
        row = cur.fetchone()
        if row:
            return _row_to_bar(row)
        cur = conn.execute(
            """
            SELECT netuid, block, provider, ts_ms, registered_at, price_tao, unit, quality,
                   schema_version, block_hash, series_key
            FROM chain_price_samples
            WHERE series_key = ? AND registered_at = ? AND quality != 'disputed'
              AND ts_ms > ? AND ts_ms <= ?
            ORDER BY ts_ms ASC
            LIMIT 1
            """,
            (series_key, registered_at, resolve_at_ms, resolve_at_ms + half),
        )
        row = cur.fetchone()
        if row:
            return _row_to_bar(row)
    return None


def _row_to_bar(row: tuple) -> Dict[str, Any]:
    return {
        "netuid": row[0],
        "block": row[1],
        "provider": row[2],
        "ts_ms": row[3],
        "registered_at": row[4],
        "price_tao": row[5],
        "unit": row[6],
        "quality": row[7],
        "schema_version": row[8],
        "block_hash": row[9],
        "series_key": row[10],
    }


def prune_old_rows(path: Optional[str] = None) -> Dict[str, int]:
    """Light per-tick prune: row cap only (hourly job handles age downsampling)."""
    db_path = path or CHAIN_PRICE_DB_PATH
    deleted_samples = 0
    deleted_blocks = 0
    with db_conn(db_path) as conn:
        cur = conn.execute("SELECT COUNT(*) FROM chain_price_samples")
        total = int(cur.fetchone()[0])
        if total > ROW_CAP:
            overflow = total - ROW_CAP
            conn.execute(
                """
                DELETE FROM chain_price_samples WHERE rowid IN (
                    SELECT rowid FROM chain_price_samples ORDER BY ts_ms ASC LIMIT ?
                )
                """,
                (overflow,),
            )
            deleted_samples += overflow
        conn.commit()
    return {"deleted_samples": deleted_samples, "deleted_blocks": deleted_blocks}


def run_hourly_prune_job(path: Optional[str] = None) -> Dict[str, int]:
    """Age retention: full resolution for RETENTION_FULL_DAYS, then hourly buckets."""
    db_path = path or CHAIN_PRICE_DB_PATH
    now_ms = int(time.time() * 1000)
    full_cutoff = now_ms - RETENTION_FULL_DAYS * 86400 * 1000
    age_cutoff = now_ms - RETENTION_DAYS * 86400 * 1000
    deleted_samples = 0
    deleted_blocks = 0
    with db_conn(db_path) as conn:
        cur = conn.execute("DELETE FROM chain_price_samples WHERE ts_ms < ?", (age_cutoff,))
        deleted_samples += cur.rowcount
        conn.execute(
            """
            DELETE FROM chain_price_samples
            WHERE ts_ms >= ? AND ts_ms < ?
              AND rowid NOT IN (
                SELECT MIN(rowid) FROM chain_price_samples
                WHERE ts_ms >= ? AND ts_ms < ?
                GROUP BY netuid, provider, (ts_ms / 3600000)
              )
            """,
            (age_cutoff, full_cutoff, age_cutoff, full_cutoff),
        )
        deleted_samples += conn.total_changes
        cur = conn.execute(
            """
            DELETE FROM chain_blocks
            WHERE ts_ms < ?
               OR block NOT IN (SELECT DISTINCT block FROM chain_price_samples)
            """,
            (age_cutoff,),
        )
        deleted_blocks += cur.rowcount
        conn.execute("PRAGMA incremental_vacuum")
        conn.commit()
    stats = prune_old_rows(path=db_path)
    deleted_samples += stats["deleted_samples"]
    return {"deleted_samples": deleted_samples, "deleted_blocks": deleted_blocks}
