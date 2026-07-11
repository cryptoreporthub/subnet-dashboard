"""SQLite engine for durable trace / disposition / lineage storage (Phase F)."""

from __future__ import annotations

import os
import sqlite3
from typing import Optional

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


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    db_path = ensure_db_dir(path)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    conn.commit()
