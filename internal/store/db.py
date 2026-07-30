"""SQLite engine for durable trace / disposition / lineage storage (Phase F).

Uses shared WAL connections + per-path locking via fetchers._sqlite (§31-8).
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

from fetchers._sqlite import db_conn as _shared_db_conn
from fetchers._sqlite import get_connection

STORE_DB_PATH = os.environ.get("STORE_DB_PATH", "data/store.db")

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS trail_rows (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    decision_type TEXT,
    decision_json TEXT NOT NULL DEFAULT '{}',
    signals_json TEXT NOT NULL DEFAULT '[]',
    subnet TEXT,
    netuid INTEGER
);

CREATE TABLE IF NOT EXISTS dispositions (
    netuid INTEGER PRIMARY KEY,
    action TEXT NOT NULL,
    score REAL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS decision_lineage (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    total_records INTEGER NOT NULL DEFAULT 0,
    top_signal_types_json TEXT NOT NULL DEFAULT '[]',
    last_record_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_trail_rows_created_at ON trail_rows(created_at);
CREATE INDEX IF NOT EXISTS idx_trail_rows_decision_type ON trail_rows(decision_type);
"""


def ensure_db_dir(path: Optional[str] = None) -> str:
    db_path = path or STORE_DB_PATH
    directory = os.path.dirname(db_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    return db_path


@contextmanager
def db_conn(path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    """Shared WAL connection with per-path lock. Do not close the connection."""
    db_path = ensure_db_dir(path)
    with _shared_db_conn(db_path) as conn:
        conn.row_factory = sqlite3.Row
        yield conn


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    """Return shared WAL connection (prefer ``db_conn`` context manager)."""
    db_path = ensure_db_dir(path)
    # Acquire via helper so lock+WAL apply; caller using bare connect() without
    # the lock is discouraged — use db_conn().
    conn = get_connection(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    conn.commit()
