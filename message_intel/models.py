"""
SQLite database models for the Message Intelligence pipeline.

Stores messages, metrics, analysis results, verdicts, price snapshots,
outcomes, author reliability, and pattern correlations.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


DB_PATH = os.environ.get("MESSAGE_INTEL_DB", "data/message_intel.db")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """SQLite-backed persistence for the message intelligence pipeline."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    group_id TEXT,
                    group_name TEXT,
                    author_id TEXT,
                    author_name TEXT,
                    author_username TEXT,
                    content TEXT,
                    timestamp TEXT,
                    raw_json TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS message_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL REFERENCES messages(id),
                    views INTEGER DEFAULT 0,
                    forwards INTEGER DEFAULT 0,
                    replies INTEGER DEFAULT 0,
                    reactions TEXT
                );

                CREATE TABLE IF NOT EXISTS message_analysis (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL REFERENCES messages(id),
                    sentiment TEXT,
                    sentiment_confidence REAL,
                    hype_score REAL,
                    substance_score REAL,
                    influence_score REAL,
                    entities_json TEXT
                );

                CREATE TABLE IF NOT EXISTS message_verdicts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL REFERENCES messages(id),
                    verdict TEXT,
                    conviction REAL,
                    reasoning TEXT,
                    predicted_direction TEXT,
                    predicted_magnitude REAL,
                    predicted_timeframe TEXT,
                    predicted_confidence REAL
                );

                CREATE TABLE IF NOT EXISTS price_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL REFERENCES messages(id),
                    tao_usd_price REAL,
                    netuid INTEGER,
                    snapshot_timestamp TEXT
                );

                CREATE TABLE IF NOT EXISTS price_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL REFERENCES messages(id),
                    price_1h REAL,
                    price_4h REAL,
                    price_24h REAL,
                    price_7d REAL,
                    pump_pct_max REAL,
                    time_to_pump REAL,
                    pump_duration REAL,
                    resurgence REAL,
                    outcome TEXT
                );

                CREATE TABLE IF NOT EXISTS author_reliability (
                    author_id TEXT PRIMARY KEY,
                    author_name TEXT,
                    total_messages INTEGER DEFAULT 0,
                    correct_predictions INTEGER DEFAULT 0,
                    accuracy_score REAL DEFAULT 0.0
                );

                CREATE TABLE IF NOT EXISTS pattern_correlations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern_description TEXT,
                    match_count INTEGER DEFAULT 0,
                    success_rate REAL DEFAULT 0.0,
                    confidence REAL DEFAULT 0.0
                );

                CREATE INDEX IF NOT EXISTS idx_messages_source ON messages(source);
                CREATE INDEX IF NOT EXISTS idx_messages_author ON messages(author_id);
                CREATE INDEX IF NOT EXISTS idx_verdicts_message ON message_verdicts(message_id);
                CREATE INDEX IF NOT EXISTS idx_outcomes_message ON price_outcomes(message_id);
            """)
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """Add columns introduced after initial schema (idempotent)."""
        with self._connect() as conn:
            cols = {
                r[1] for r in conn.execute("PRAGMA table_info(price_snapshots)").fetchall()
            }
            if "netuid" not in cols:
                try:
                    conn.execute("ALTER TABLE price_snapshots ADD COLUMN netuid INTEGER")
                except sqlite3.OperationalError:
                    pass

    # ── Messages ──────────────────────────────────────────────────────

    def save_message(self, msg: Dict[str, Any]) -> int:
        raw = {k: v for k, v in msg.items() if k != "metrics"}
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO messages (source, group_id, group_name, author_id,
                   author_name, author_username, content, timestamp, raw_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    msg.get("source", "telegram"),
                    msg.get("group_id"),
                    msg.get("group_name"),
                    msg.get("author_id"),
                    msg.get("author_name"),
                    msg.get("author_username"),
                    msg.get("content"),
                    msg.get("timestamp"),
                    json.dumps(raw),
                ),
            )
            message_id = cur.lastrowid

            metrics = msg.get("metrics")
            if metrics:
                conn.execute(
                    """INSERT INTO message_metrics (message_id, views, forwards, replies, reactions)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        message_id,
                        metrics.get("views", 0),
                        metrics.get("forwards", 0),
                        metrics.get("replies", 0),
                        json.dumps(metrics.get("reactions", {})),
                    ),
                )
            return message_id

    def get_message(self, message_id: int) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            # Attach metrics, analysis, verdict, price
            result["metrics"] = self._get_metrics(conn, message_id)
            result["analysis"] = self._get_analysis(conn, message_id)
            result["verdict"] = self._get_verdict(conn, message_id)
            result["price_snapshot"] = self._get_price_snapshot(conn, message_id)
            result["price_outcome"] = self._get_price_outcome(conn, message_id)
            return result

    def list_messages(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM messages ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            results = []
            for row in rows:
                d = dict(row)
                d["verdict"] = self._get_verdict(conn, d["id"])
                d["analysis"] = self._get_analysis(conn, d["id"])
                results.append(d)
            return results

    # ── Analysis ──────────────────────────────────────────────────────

    def save_analysis(self, message_id: int, analysis: Dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO message_analysis (message_id, sentiment, sentiment_confidence,
                   hype_score, substance_score, influence_score, entities_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    message_id,
                    analysis.get("sentiment"),
                    analysis.get("sentiment_confidence"),
                    analysis.get("hype_score"),
                    analysis.get("substance_score"),
                    analysis.get("influence_score"),
                    json.dumps(analysis.get("entities", {})),
                ),
            )

    # ── Verdicts ──────────────────────────────────────────────────────

    def save_verdict(self, message_id: int, verdict: Dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO message_verdicts (message_id, verdict, conviction, reasoning,
                   predicted_direction, predicted_magnitude, predicted_timeframe, predicted_confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    message_id,
                    verdict.get("verdict"),
                    verdict.get("conviction"),
                    verdict.get("reasoning"),
                    verdict.get("predicted_direction"),
                    verdict.get("predicted_magnitude"),
                    verdict.get("predicted_timeframe"),
                    verdict.get("predicted_confidence"),
                ),
            )

    # ── Price ─────────────────────────────────────────────────────────

    def save_price_snapshot(self, message_id: int, price: float, netuid: Optional[int] = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO price_snapshots (message_id, tao_usd_price, netuid, snapshot_timestamp)
                   VALUES (?, ?, ?, ?)""",
                (message_id, price, netuid, _now_iso()),
            )

    def save_price_outcome(self, message_id: int, outcome: Dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO price_outcomes (message_id, price_1h, price_4h, price_24h, price_7d,
                   pump_pct_max, time_to_pump, pump_duration, resurgence, outcome)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    message_id,
                    outcome.get("price_1h"),
                    outcome.get("price_4h"),
                    outcome.get("price_24h"),
                    outcome.get("price_7d"),
                    outcome.get("pump_pct_max"),
                    outcome.get("time_to_pump"),
                    outcome.get("pump_duration"),
                    outcome.get("resurgence"),
                    outcome.get("outcome"),
                ),
            )

    # ── Author Reliability ────────────────────────────────────────────

    def upsert_author_reliability(self, author: Dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO author_reliability (author_id, author_name, total_messages,
                   correct_predictions, accuracy_score)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(author_id) DO UPDATE SET
                       author_name = excluded.author_name,
                       total_messages = excluded.total_messages,
                       correct_predictions = excluded.correct_predictions,
                       accuracy_score = excluded.accuracy_score""",
                (
                    author.get("author_id"),
                    author.get("author_name"),
                    author.get("total_messages", 0),
                    author.get("correct_predictions", 0),
                    author.get("accuracy_score", 0.0),
                ),
            )

    # ── Pattern Correlations ──────────────────────────────────────────

    def save_pattern(self, pattern: Dict[str, Any]) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO pattern_correlations (pattern_description, match_count, success_rate, confidence)
                   VALUES (?, ?, ?, ?)""",
                (
                    pattern.get("pattern_description"),
                    pattern.get("match_count", 0),
                    pattern.get("success_rate", 0.0),
                    pattern.get("confidence", 0.0),
                ),
            )
            return cur.lastrowid

    def list_patterns(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pattern_correlations ORDER BY confidence DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def list_high_conviction_messages(self, min_conviction: float = 0.6) -> List[Dict[str, Any]]:
        """Return messages whose verdict conviction >= threshold."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT m.*, v.conviction, v.verdict, v.predicted_direction
                   FROM messages m
                   JOIN message_verdicts v ON v.message_id = m.id
                   WHERE v.conviction >= ?
                   ORDER BY v.conviction DESC""",
                (min_conviction,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_unresolved_outcomes(self) -> List[Dict[str, Any]]:
        """Return messages with a price snapshot but no 24h outcome yet."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT m.*, ps.tao_usd_price, ps.netuid, ps.snapshot_timestamp
                   FROM messages m
                   JOIN price_snapshots ps ON ps.message_id = m.id
                   LEFT JOIN price_outcomes po ON po.message_id = m.id
                   WHERE po.id IS NULL
                   ORDER BY m.id""",
            ).fetchall()
            return [dict(r) for r in rows]

    def list_price_outcomes(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recorded price outcomes (most recent first)."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT po.*, ps.netuid
                   FROM price_outcomes po
                   LEFT JOIN price_snapshots ps ON ps.message_id = po.message_id
                   ORDER BY po.id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Private helpers ───────────────────────────────────────────────

    @staticmethod
    def _get_metrics(conn: sqlite3.Connection, message_id: int) -> Optional[Dict]:
        row = conn.execute(
            "SELECT * FROM message_metrics WHERE message_id = ?", (message_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _get_analysis(conn: sqlite3.Connection, message_id: int) -> Optional[Dict]:
        row = conn.execute(
            "SELECT * FROM message_analysis WHERE message_id = ?", (message_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _get_verdict(conn: sqlite3.Connection, message_id: int) -> Optional[Dict]:
        row = conn.execute(
            "SELECT * FROM message_verdicts WHERE message_id = ?", (message_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _get_price_snapshot(conn: sqlite3.Connection, message_id: int) -> Optional[Dict]:
        row = conn.execute(
            "SELECT * FROM price_snapshots WHERE message_id = ?", (message_id,)
        ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _get_price_outcome(conn: sqlite3.Connection, message_id: int) -> Optional[Dict]:
        row = conn.execute(
            "SELECT * FROM price_outcomes WHERE message_id = ?", (message_id,)
        ).fetchone()
        return dict(row) if row else None