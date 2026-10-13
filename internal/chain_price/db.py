"""SQLite persistence for forward chain price samples."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from internal.chain_price.config import CHAIN_PRICE_DB_PATH, RETENTION_DAYS, ROW_CAP
from internal.store.db import db_conn, ensure_db_dir

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
    PRIMARY KEY (netuid, block, provider)
);

CREATE INDEX IF NOT EXISTS idx_chain_price_samples_block ON chain_price_samples(block);
CREATE INDEX IF NOT EXISTS idx_chain_price_samples_ts ON chain_price_samples(ts_ms);
"""


def ensure_schema(path: Optional[str] = None) -> str:
    db_path = ensure_db_dir(path or CHAIN_PRICE_DB_PATH)
    with db_conn(db_path) as conn:
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
    return db_path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        conn.executemany(
            """
            INSERT OR IGNORE INTO chain_price_samples
            (netuid, block, provider, ts_ms, registered_at, tao_reserve_raw, alpha_reserve_raw,
             price_tao, spot_price_tao, unit, quality, schema_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                )
                for r in payload
            ],
        )
        conn.commit()
    return len(payload)


def prune_old_rows(path: Optional[str] = None) -> Dict[str, int]:
    """Enforce retention window and hard row cap."""
    db_path = path or CHAIN_PRICE_DB_PATH
    cutoff_ms = int(time.time() * 1000) - RETENTION_DAYS * 86400 * 1000
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
        cur = conn.execute(
            "DELETE FROM chain_price_samples WHERE ts_ms < ?", (cutoff_ms,)
        )
        deleted_samples += cur.rowcount
        cur = conn.execute(
            """
            DELETE FROM chain_blocks
            WHERE ts_ms < ?
               OR block NOT IN (SELECT DISTINCT block FROM chain_price_samples)
            """,
            (cutoff_ms,),
        )
        deleted_blocks += cur.rowcount
        conn.commit()
    return {"deleted_samples": deleted_samples, "deleted_blocks": deleted_blocks}
