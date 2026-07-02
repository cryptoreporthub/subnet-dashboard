"""
SQLite-backed canonical trace store for the Council engine.

All council decisions are logged as append-only records, making the trace
the source of truth for:
- CouncilRun: Each council decision cycle
- SignalRecord: Signals from experts
- DecisionRecord: Final decisions
- JudgeVerdict: Judge reviews
- LearningUpdate: Weight updates
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Generator

# Database path
TRACE_DB_PATH = os.environ.get("TRACE_DB_PATH", "data/council_trace.db")

# Schema version
SCHEMA_VERSION = 1


class TraceStore:
    """SQLite-backed trace store for Council decisions."""

    _instance: Optional["TraceStore"] = None
    _lock = threading.Lock()

    def __init__(self, db_path: str = TRACE_DB_PATH):
        self.db_path = db_path
        self._local = threading.local()
        self._ensure_schema()

    @classmethod
    def get_instance(cls, db_path: str = TRACE_DB_PATH) -> "TraceStore":
        """Get singleton instance."""
        with cls._lock:
            # Always create new instance if path differs
            if cls._instance is None or cls._instance.db_path != db_path:
                cls._instance = cls(db_path)
            return cls._instance

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local connection."""
        if not hasattr(self._local, "conn"):
            os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
            self._local.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for atomic transactions."""
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _ensure_schema(self) -> None:
        """Create tables if they don't exist."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Schema version table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL
            )
            """)
        
        cursor.execute("SELECT version FROM schema_version")
        row = cursor.fetchone()
        if row is None:
            cursor.execute(f"INSERT INTO schema_version (version) VALUES ({SCHEMA_VERSION})")
            conn.commit()

        # CouncilRun table - each council decision cycle
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS council_run (
                id TEXT PRIMARY KEY,
                run_at TEXT NOT NULL,
                subnet_id INTEGER,
                subnet_name TEXT,
                horizon TEXT,
                total_score REAL,
                confidence REAL,
                final_action TEXT,
                final_confidence REAL,
                created_at TEXT NOT NULL
            )
            """)

        # SignalRecord table - signals from experts
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signal_record (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                expert TEXT NOT NULL,
                signal_type TEXT,
                score REAL,
                contribution REAL,
                metadata TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES council_run(id)
            )
            """)

        # DecisionRecord table - final decisions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS decision_record (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                decision_type TEXT,
                action TEXT,
                confidence REAL,
                rationale TEXT,
                metadata TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES council_run(id)
            )
            """)

        # JudgeVerdict table - judge reviews
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS judge_verdict (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                judge_name TEXT,
                approved INTEGER,
                concerns TEXT,
                adjusted_confidence REAL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES council_run(id)
            )
            """)

        # LearningUpdate table - weight updates
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS learning_update (
                id TEXT PRIMARY KEY,
                run_id TEXT,
                expert TEXT,
                old_weight REAL,
                new_weight REAL,
                delta REAL,
                reason TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES council_run(id)
            )
            """)

        # EvidenceRecord table - scout findings
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS evidence_record (
                id TEXT PRIMARY KEY,
                run_id TEXT,
                source TEXT,
                url TEXT,
                title TEXT,
                content TEXT,
                relevance_score REAL,
                metadata TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (run_id) REFERENCES council_run(id)
            )
            """)

        conn.commit()

    def create_run(
        self,
        subnet_id: Optional[int] = None,
        subnet_name: Optional[str] = None,
        horizon: Optional[str] = None,
        total_score: Optional[float] = None,
        confidence: Optional[float] = None,
        final_action: Optional[str] = None,
        final_confidence: Optional[float] = None,
    ) -> str:
        """Create a new council run and return its ID."""
        run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        now = datetime.now(timezone.utc).isoformat()

        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO council_run (
                    id, run_at, subnet_id, subnet_name, horizon,
                    total_score, confidence, final_action, final_confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    now,
                    subnet_id,
                    subnet_name,
                    horizon,
                    total_score,
                    confidence,
                    final_action,
                    final_confidence,
                    now,
                ),
            )

        return run_id

    def add_signal(
        self,
        run_id: str,
        expert: str,
        signal_type: Optional[str] = None,
        score: Optional[float] = None,
        contribution: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Add a signal record to a run."""
        signal_id = f"sig_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        now = datetime.now(timezone.utc).isoformat()

        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO signal_record (
                    id, run_id, expert, signal_type, score, contribution, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal_id,
                    run_id,
                    expert,
                    signal_type,
                    score,
                    contribution,
                    json.dumps(metadata) if metadata else None,
                    now,
                ),
            )

        return signal_id

    def add_decision(
        self,
        run_id: str,
        decision_type: str,
        action: str,
        confidence: Optional[float] = None,
        rationale: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Add a decision record to a run."""
        decision_id = f"dec_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        now = datetime.now(timezone.utc).isoformat()

        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO decision_record (
                    id, run_id, decision_type, action, confidence, rationale, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    run_id,
                    decision_type,
                    action,
                    confidence,
                    rationale,
                    json.dumps(metadata) if metadata else None,
                    now,
                ),
            )

        return decision_id

    def add_judge_verdict(
        self,
        run_id: str,
        judge_name: str,
        approved: bool,
        concerns: Optional[List[str]] = None,
        adjusted_confidence: Optional[float] = None,
    ) -> str:
        """Add a judge verdict to a run."""
        verdict_id = f"ver_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        now = datetime.now(timezone.utc).isoformat()

        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO judge_verdict (
                    id, run_id, judge_name, approved, concerns, adjusted_confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    verdict_id,
                    run_id,
                    judge_name,
                    1 if approved else 0,
                    json.dumps(concerns) if concerns else None,
                    adjusted_confidence,
                    now,
                ),
            )

        return verdict_id

    def add_learning_update(
        self,
        run_id: Optional[str],
        expert: str,
        old_weight: float,
        new_weight: float,
        reason: Optional[str] = None,
    ) -> str:
        """Add a learning update (weight change)."""
        update_id = f"upd_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        now = datetime.now(timezone.utc).isoformat()

        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO learning_update (
                    id, run_id, expert, old_weight, new_weight, delta, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    update_id,
                    run_id,
                    expert,
                    old_weight,
                    new_weight,
                    new_weight - old_weight,
                    reason,
                    now,
                ),
            )

        return update_id

    def add_evidence(
        self,
        run_id: Optional[str],
        source: str,
        url: Optional[str] = None,
        title: Optional[str] = None,
        content: Optional[str] = None,
        relevance_score: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Add an evidence record (from scout)."""
        evidence_id = f"ev_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}"
        now = datetime.now(timezone.utc).isoformat()

        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO evidence_record (
                    id, run_id, source, url, title, content, relevance_score, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    run_id,
                    source,
                    url,
                    title,
                    content,
                    relevance_score,
                    json.dumps(metadata) if metadata else None,
                    now,
                ),
            )

        return evidence_id

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get a run with all its records."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM council_run WHERE id = ?", (run_id,))
        run_row = cursor.fetchone()
        if run_row is None:
            return None

        run = dict(run_row)

        # Get signals
        cursor.execute("SELECT * FROM signal_record WHERE run_id = ?", (run_id,))
        run["signals"] = [dict(row) for row in cursor.fetchall()]

        # Get decisions
        cursor.execute("SELECT * FROM decision_record WHERE run_id = ?", (run_id,))
        run["decisions"] = [dict(row) for row in cursor.fetchall()]

        # Get verdicts
        cursor.execute("SELECT * FROM judge_verdict WHERE run_id = ?", (run_id,))
        run["verdicts"] = [dict(row) for row in cursor.fetchall()]

        # Get learning updates
        cursor.execute("SELECT * FROM learning_update WHERE run_id = ?", (run_id,))
        run["learning_updates"] = [dict(row) for row in cursor.fetchall()]

        # Get evidence
        cursor.execute("SELECT * FROM evidence_record WHERE run_id = ?", (run_id,))
        run["evidence"] = [dict(row) for row in cursor.fetchall()]

        return run

    def get_recent_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent runs (without full details)."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM council_run ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def get_evidence(
        self,
        query: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get evidence records, optionally filtered by query."""
        conn = self._get_connection()
        cursor = conn.cursor()

        if query:
            cursor.execute(
                """
                SELECT * FROM evidence_record
                WHERE content LIKE ? OR title LIKE ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (f"%{query}%", f"%{query}%", limit),
            )
        else:
            cursor.execute(
                "SELECT * FROM evidence_record ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )

        return [dict(row) for row in cursor.fetchall()]

    def get_expert_weights_history(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get weight history per expert."""
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT expert, old_weight, new_weight, created_at
            FROM learning_update
            ORDER BY created_at ASC
        """)

        history: Dict[str, List[Dict[str, Any]]] = {}
        for row in cursor.fetchall():
            expert = row["expert"]
            if expert not in history:
                history[expert] = []
            history[expert].append({
                "old_weight": row["old_weight"],
                "new_weight": row["new_weight"],
                "created_at": row["created_at"],
            })

        return history


# Global instance accessor
def get_trace_store(db_path: str = TRACE_DB_PATH) -> TraceStore:
    """Get the global trace store instance."""
    return TraceStore.get_instance(db_path)