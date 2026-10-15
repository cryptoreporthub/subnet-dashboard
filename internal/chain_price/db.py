"""SQLite persistence for forward chain price samples."""

from __future__ import annotations

import logging
import os
import sqlite3
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

# Free pages returned per hourly run. Bounded so one run stays short; a backlog drains over runs.
VACUUM_PAGES_PER_RUN = 2000

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
    if not cols:  # table not created yet; the schema script creates it at the current version
        return
    if "block_hash" not in cols:
        conn.execute("ALTER TABLE chain_price_samples ADD COLUMN block_hash TEXT")
    if "series_key" not in cols:
        conn.execute("ALTER TABLE chain_price_samples ADD COLUMN series_key TEXT")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return row is not None


def count_chain_price_samples(path: Optional[str] = None) -> int:
    db_path = path or CHAIN_PRICE_DB_PATH
    if not os.path.exists(db_path):
        return 0
    with db_conn(db_path) as conn:
        if not _table_exists(conn, "chain_price_samples"):
            return 0
        return int(conn.execute("SELECT COUNT(*) FROM chain_price_samples").fetchone()[0])


def can_accept_sample_batch(batch_size: int, path: Optional[str] = None) -> bool:
    """True when ``batch_size`` new rows fit without post-insert prune evicting overflow."""
    if batch_size < 0:
        return False
    return count_chain_price_samples(path) + batch_size <= ROW_CAP


def ensure_schema(path: Optional[str] = None) -> str:
    db_path = ensure_db_dir(path or CHAIN_PRICE_DB_PATH)
    with db_conn(db_path) as conn:
        # auto_vacuum only takes effect before the first table is created, or after a VACUUM
        # rewrites an existing file. Set it first, then VACUUM once if the file was created before.
        if conn.execute("PRAGMA auto_vacuum").fetchone()[0] != 2:
            conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
            try:
                conn.execute("VACUUM")
            except sqlite3.OperationalError as exc:
                # Not fatal: the file keeps its old auto_vacuum mode and retention still runs.
                logger.warning("chain price db VACUUM skipped: %s", exc)
        # Migrate before the schema script: its indexes reference v2 columns that a v1 file lacks.
        _migrate_columns(conn)
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
    return db_path


def load_anchor_blocks(
    ts_ms: int,
    window_ms: int,
    path: Optional[str] = None,
) -> List[int]:
    """``chain_blocks`` rows near ``ts_ms`` for bracketed resolve seeding."""
    low = ts_ms - window_ms
    high = ts_ms + window_ms
    db_path = path or CHAIN_PRICE_DB_PATH
    if not os.path.exists(db_path):
        return []
    with db_conn(db_path) as conn:
        if not _table_exists(conn, "chain_blocks"):
            return []
        cur = conn.execute(
            """
            SELECT block FROM chain_blocks
            WHERE ts_ms BETWEEN ? AND ?
            ORDER BY ts_ms
            """,
            (low, high),
        )
        return [int(row[0]) for row in cur.fetchall()]


def has_row_cap_headroom(path: Optional[str] = None) -> bool:
    """False when even a single-row insert would require post-write prune (fail closed)."""
    return can_accept_sample_batch(1, path=path)


def _backfill_bucket_distinct_netuid_count(
    conn: sqlite3.Connection,
    block: int,
) -> int:
    return int(
        conn.execute(
            """
            SELECT COUNT(DISTINCT netuid) FROM chain_price_samples
            WHERE block = ? AND quality = 'chain_sampled'
            """,
            (block,),
        ).fetchone()[0]
    )


def hourly_bucket_has_chain_sample(
    bucket_ts_ms: int,
    path: Optional[str] = None,
) -> bool:
    """True when a backfill ``chain_blocks`` marker exists with full distinct netuid coverage."""
    db_path = path or CHAIN_PRICE_DB_PATH
    if not os.path.exists(db_path):
        return False
    with db_conn(db_path) as conn:
        if not _table_exists(conn, "chain_blocks") or not _table_exists(
            conn, "chain_price_samples"
        ):
            return False
        row = conn.execute(
            """
            SELECT block, n_subnets FROM chain_blocks
            WHERE bucket_ts = ? AND kind = 'backfill'
            LIMIT 1
            """,
            (bucket_ts_ms,),
        ).fetchone()
        if not row:
            return False
        block, n_subnets = int(row[0]), int(row[1])
        distinct_netuids = _backfill_bucket_distinct_netuid_count(conn, block)
        return distinct_netuids >= n_subnets


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
        # Keep one row per series per hour, preferring non-disputed rows. Partition by the full
        # series identity: a netuid/provider/hour key alone merged separate registrations.
        cur = conn.execute(
            """
            DELETE FROM chain_price_samples WHERE rowid IN (
              SELECT rowid FROM (
                SELECT rowid, ROW_NUMBER() OVER (
                  PARTITION BY netuid, provider, series_key, registered_at, (ts_ms / 3600000)
                  ORDER BY CASE WHEN quality = 'disputed' THEN 1 ELSE 0 END, ts_ms, rowid
                ) AS rn
                FROM chain_price_samples WHERE ts_ms >= ? AND ts_ms < ?
              ) WHERE rn > 1)
            """,
            (age_cutoff, full_cutoff),
        )
        deleted_samples += cur.rowcount
        cur = conn.execute(
            """
            DELETE FROM chain_blocks
            WHERE ts_ms < ?
               OR block NOT IN (SELECT DISTINCT block FROM chain_price_samples)
            """,
            (age_cutoff,),
        )
        deleted_blocks += cur.rowcount
        conn.commit()
    stats = prune_old_rows(path=db_path)
    deleted_samples += stats["deleted_samples"]
    with db_conn(db_path) as conn:
        incremental_vacuum(conn, VACUUM_PAGES_PER_RUN)
    return {"deleted_samples": deleted_samples, "deleted_blocks": deleted_blocks}


def incremental_vacuum(conn: sqlite3.Connection, pages: int) -> int:
    """Return up to ``pages`` free pages to the OS. Returns the count actually reclaimed.

    ``PRAGMA incremental_vacuum(N)`` only executes when its rows are fetched; an unfetched
    PRAGMA steps once. The page bound keeps one hourly run from holding the write lock for long.
    """
    if conn.execute("PRAGMA auto_vacuum").fetchone()[0] != 2:
        return 0
    before = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
    conn.execute(f"PRAGMA incremental_vacuum({int(pages)})").fetchall()
    after = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
    return max(0, before - after)
