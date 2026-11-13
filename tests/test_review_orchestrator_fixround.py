from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import tools.review_orchestrator.deadman as deadman
import tools.review_orchestrator.exam_v0 as exam_v0
import tools.review_orchestrator.persist as persist
from tools.review_orchestrator import db
from tools.review_orchestrator.db import DuplicateTickIdError


def _create_store_missing_duration_check(state_dir: Path) -> Path:
    store = db.db_path(state_dir)
    conn = sqlite3.connect(store)
    conn.executescript(
        """
        CREATE TABLE ticks (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            tick_id TEXT NOT NULL UNIQUE,
            started_at TEXT NOT NULL CHECK (length(started_at) BETWEEN 20 AND 40),
            duration_ms INTEGER,
            outcome TEXT NOT NULL DEFAULT 'running'
                CHECK (outcome IN ('running', 'completed', 'failed', 'abandoned')),
            noop INTEGER NOT NULL DEFAULT 0 CHECK (noop IN (0, 1)),
            overlap INTEGER NOT NULL DEFAULT 0 CHECK (overlap IN (0, 1)),
            last_alert_ok INTEGER CHECK (last_alert_ok IS NULL OR last_alert_ok IN (0, 1)),
            CHECK ((outcome IN ('running', 'abandoned')) = (duration_ms IS NULL))
        );
        """
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO ticks "
        "(tick_id, started_at, duration_ms, outcome, noop, overlap, last_alert_ok) "
        "VALUES ('invalid', ?, -1, 'completed', 0, 0, 1)",
        (now,),
    )
    conn.execute(db._VIEW_SQL)
    conn.commit()
    conn.close()
    return store


def test_repair_rejects_ticks_table_missing_duration_check(
    tmp_path: Path,
) -> None:
    store = _create_store_missing_duration_check(tmp_path)

    moved = persist.repair_store(tmp_path, stamp="missing-checks")

    assert moved != store
    assert moved.is_file()
    assert not store.exists()
    assert not deadman.evaluate_deadman(tmp_path).ok


def test_repair_keeps_pre_alias_legacy_latest_view(tmp_path: Path) -> None:
    persist.run_tick(tmp_path, tick_id="legacy-seed", noop=True)
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(store)
    conn.execute("DROP VIEW latest")
    conn.execute(
        "CREATE VIEW latest AS SELECT seq, tick_id, started_at, duration_ms, "
        "outcome, noop, overlap, last_alert_ok FROM ticks "
        "ORDER BY seq DESC LIMIT 1"
    )
    conn.commit()
    conn.close()

    repaired = persist.repair_store(tmp_path, stamp="legacy-view")

    assert repaired == store
    assert persist.read_latest_tick(tmp_path)["tick_id"] == "legacy-seed"


def test_repair_keeps_unrelated_safe_view(tmp_path: Path) -> None:
    persist.run_tick(tmp_path, tick_id="view-seed", noop=True)
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(store)
    conn.execute("CREATE TABLE auxiliary (value TEXT)")
    conn.execute("CREATE VIEW auxiliary_values AS SELECT value FROM auxiliary")
    conn.commit()
    conn.close()

    repaired = persist.repair_store(tmp_path, stamp="unrelated-view")

    assert repaired == store
    assert persist.read_latest_tick(tmp_path)["tick_id"] == "view-seed"


def test_repair_keeps_unrelated_audit_trigger(tmp_path: Path) -> None:
    persist.run_tick(tmp_path, tick_id="trigger-seed", noop=True)
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(store)
    conn.executescript(
        """
        CREATE TABLE auxiliary (value TEXT);
        CREATE TABLE audit_log (value TEXT);
        CREATE TRIGGER audit_aux AFTER INSERT ON auxiliary
        BEGIN INSERT INTO audit_log(value) VALUES (NEW.value); END;
        """
    )
    conn.commit()
    conn.close()

    repaired = persist.repair_store(tmp_path, stamp="unrelated-trigger")

    assert repaired == store
    conn = sqlite3.connect(store)
    try:
        conn.execute("INSERT INTO auxiliary(value) VALUES ('kept')")
        assert conn.execute("SELECT value FROM audit_log").fetchall() == [("kept",)]
    finally:
        conn.close()
    assert persist.read_latest_tick(tmp_path)["tick_id"] == "trigger-seed"


def test_repair_cli_reports_missing_store_intent_as_exit_two(
    tmp_path: Path, capsys
) -> None:
    tmp_path.mkdir(exist_ok=True)
    db._repair_intent_path(tmp_path).write_text(
        json.dumps(
            {
                "version": 1,
                "target": "orchestrator.sqlite.corrupt-missing",
                "files": ["main"],
            }
        ),
        encoding="utf-8",
    )

    result = persist.main(["repair", "--state-dir", str(tmp_path)])

    assert result == 2
    assert "repair: blocked:" in capsys.readouterr().err
    assert db._repair_intent_path(tmp_path).is_file()


def test_repair_cli_reports_busy_store_as_exit_two(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    persist.run_tick(tmp_path, tick_id="busy-seed", noop=True)
    store = db.db_path(tmp_path)
    before = store.read_bytes()
    monkeypatch.setattr(db, "BUSY_TIMEOUT_MS", 1)
    conn = sqlite3.connect(store, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")

        result = persist.main(["repair", "--state-dir", str(tmp_path)])

        assert result == 2
        assert "locked" in capsys.readouterr().err.lower()
        assert store.read_bytes() == before
    finally:
        conn.execute("ROLLBACK")
        conn.close()


def test_complete_tick_reports_abandoned_without_overwriting(
    tmp_path: Path,
) -> None:
    stale = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    conn = db.connect(tmp_path)
    try:
        cursor = conn.execute(
            "INSERT INTO ticks (tick_id, started_at, outcome, overlap) "
            "VALUES ('straggler', ?, 'running', 0)",
            (stale,),
        )
        seq = int(cursor.lastrowid)
    finally:
        conn.close()

    persist.run_tick(tmp_path, tick_id="sweeper", noop=True)
    conn = db.connect(tmp_path)
    try:
        assert tuple(
            conn.execute(
                "SELECT outcome, duration_ms FROM ticks WHERE seq=?", (seq,)
            ).fetchone()
        ) == ("abandoned", None)
        assert (
            db.complete_tick(
                conn,
                seq,
                outcome="completed",
                duration_ms=2500,
                noop=False,
            )
            == "abandoned"
        )
        assert tuple(
            conn.execute(
                "SELECT outcome, duration_ms FROM ticks WHERE seq=?", (seq,)
            ).fetchone()
        ) == ("abandoned", None)
    finally:
        conn.close()


def test_complete_tick_rejects_conflicting_finalized_replay(
    tmp_path: Path,
) -> None:
    result = persist.run_tick(tmp_path, tick_id="finalized", noop=False)
    conn = db.connect(tmp_path)
    try:
        before = tuple(
            conn.execute(
                "SELECT outcome, duration_ms, noop, last_alert_ok "
                "FROM ticks WHERE seq=?",
                (result.seq,),
            ).fetchone()
        )
        already_finalized = getattr(db, "TickAlreadyFinalizedError", RuntimeError)
        with pytest.raises(already_finalized, match="already finalized"):
            db.complete_tick(
                conn,
                result.seq,
                outcome="failed",
                duration_ms=12345,
                noop=False,
            )
        after = tuple(
            conn.execute(
                "SELECT outcome, duration_ms, noop, last_alert_ok "
                "FROM ticks WHERE seq=?",
                (result.seq,),
            ).fetchone()
        )
        assert after == before
    finally:
        conn.close()


def test_complete_tick_identical_replay_is_idempotent(tmp_path: Path) -> None:
    result = persist.run_tick(tmp_path, tick_id="replay", noop=False)
    conn = db.connect(tmp_path)
    try:
        before = tuple(
            conn.execute(
                "SELECT outcome, duration_ms, noop, last_alert_ok "
                "FROM ticks WHERE seq=?",
                (result.seq,),
            ).fetchone()
        )
        db.complete_tick(
            conn,
            result.seq,
            outcome=before[0],
            duration_ms=before[1],
            noop=bool(before[2]),
            last_alert_ok=before[3],
        )
        after = tuple(
            conn.execute(
                "SELECT outcome, duration_ms, noop, last_alert_ok "
                "FROM ticks WHERE seq=?",
                (result.seq,),
            ).fetchone()
        )
        assert after == before
    finally:
        conn.close()


def test_immediate_preserves_original_error_after_rollback_conflict(
    tmp_path: Path,
) -> None:
    store = db.db_path(tmp_path)
    ddl = db._TABLE_SQL.replace(
        "TEXT    NOT NULL UNIQUE,",
        "TEXT    NOT NULL UNIQUE ON CONFLICT ROLLBACK,",
    )
    conn = sqlite3.connect(store)
    conn.executescript(ddl)
    conn.execute(
        "INSERT INTO ticks (tick_id, started_at, duration_ms, outcome) "
        "VALUES ('duplicate', '2026-01-01T00:00:00+00:00', 0, 'completed')"
    )
    conn.commit()
    conn.close()

    with pytest.raises(DuplicateTickIdError):
        persist.run_tick(tmp_path, tick_id="duplicate", noop=True)


def test_ensure_wal_rejects_success_without_wal_mode() -> None:
    class Cursor:
        def fetchone(self):
            return ("delete",)

    class Connection:
        def execute(self, _sql):
            return Cursor()

    with pytest.raises(sqlite3.OperationalError, match="WAL mode"):
        db._ensure_wal(Connection(), attempts=1, timeout_ms=0)


def test_exam_v0_rejects_noncontiguous_sequence_rows(tmp_path: Path) -> None:
    conn = db.connect(tmp_path)
    try:
        now = datetime.now(timezone.utc).isoformat()
        for seq, tick_id in ((1, "one"), (3, "two"), (4, "three")):
            conn.execute(
                "INSERT INTO ticks "
                "(seq, tick_id, started_at, duration_ms, outcome, noop, overlap) "
                "VALUES (?, ?, ?, 0, 'completed', 0, 0)",
                (seq, tick_id, now),
            )
    finally:
        conn.close()

    assert not exam_v0._check_rows(tmp_path, ["one", "two", "three"])


def test_holding_writer_cleans_ready_marker(tmp_path: Path, holding_writer) -> None:
    persist.run_tick(tmp_path, tick_id="fixture-seed", noop=True)
    marker = tmp_path / ".holder-ready-cleanup"

    with holding_writer(tmp_path, "cleanup", seconds=30) as proc:
        assert marker.is_file()

    assert not marker.exists()
    assert proc.poll() is not None
    assert proc.stderr is None or proc.stderr.closed


@pytest.mark.parametrize(
    "view_sql",
    [
        "CREATE VIEW literal_label AS SELECT 'ticks' AS label FROM auxiliary",
        "CREATE VIEW auxiliary_count AS SELECT count(*) AS total FROM auxiliary",
        "CREATE VIEW latest_column AS SELECT latest FROM auxiliary",
    ],
)
def test_repair_keeps_unrelated_views_with_protected_words(
    tmp_path: Path, view_sql: str
) -> None:
    persist.run_tick(tmp_path, tick_id="view-seed", noop=True)
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(store)
    try:
        conn.execute("CREATE TABLE auxiliary (value TEXT, latest TEXT)")
        conn.execute("INSERT INTO auxiliary VALUES ('value', 'column')")
        conn.execute(view_sql)
        conn.commit()
    finally:
        conn.close()

    repaired = persist.repair_store(tmp_path, stamp="safe-protected-word-view")

    assert repaired == store
    assert persist.read_latest_tick(tmp_path)["tick_id"] == "view-seed"


def test_repair_keeps_trigger_literals_matching_protected_objects(
    tmp_path: Path,
) -> None:
    persist.run_tick(tmp_path, tick_id="trigger-seed", noop=True)
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(store)
    try:
        conn.executescript(
            """
            CREATE TABLE auxiliary (value TEXT);
            CREATE TABLE audit_log (ticks TEXT, latest TEXT, sqlite_sequence TEXT);
            CREATE TRIGGER audit_aux AFTER INSERT ON auxiliary
            BEGIN
                INSERT INTO audit_log VALUES ('ticks', 'latest', 'sqlite_sequence');
            END;
            """
        )
        conn.commit()
    finally:
        conn.close()

    repaired = persist.repair_store(tmp_path, stamp="safe-protected-word-trigger")

    assert repaired == store
    conn = sqlite3.connect(store)
    try:
        conn.execute("INSERT INTO auxiliary(value) VALUES ('kept')")
        assert conn.execute(
            "SELECT ticks, latest, sqlite_sequence FROM audit_log"
        ).fetchall() == [("ticks", "latest", "sqlite_sequence")]
    finally:
        conn.close()
    assert persist.read_latest_tick(tmp_path)["tick_id"] == "trigger-seed"


def _sweep_tick_during_work(state_dir: Path) -> None:
    conn = sqlite3.connect(db.db_path(state_dir))
    try:
        conn.execute(
            "UPDATE ticks SET started_at = '2000-01-01T00:00:00+00:00' "
            "WHERE tick_id = 'long-running'"
        )
        conn.commit()
    finally:
        conn.close()
    persist.run_tick(state_dir, tick_id="sweeper", noop=True)


def test_run_tick_returns_abandoned_outcome_when_sweep_wins(
    tmp_path: Path,
) -> None:
    result = persist.run_tick(
        tmp_path,
        tick_id="long-running",
        work=lambda: _sweep_tick_during_work(tmp_path),
    )

    assert result.outcome == "abandoned"
    conn = db.connect(tmp_path)
    try:
        rows = {
            row["tick_id"]: dict(row)
            for row in conn.execute("SELECT * FROM ticks")
        }
    finally:
        conn.close()
    assert rows["long-running"]["outcome"] == "abandoned"
    assert rows["long-running"]["duration_ms"] is None
    assert rows["sweeper"]["outcome"] == "completed"


def test_run_tick_preserves_work_error_when_sweep_wins(tmp_path: Path) -> None:
    def work() -> None:
        _sweep_tick_during_work(tmp_path)
        raise ValueError("original work failure")

    with pytest.raises(ValueError, match="original work failure"):
        persist.run_tick(tmp_path, tick_id="long-running", work=work)


def test_deadman_reads_legacy_latest_without_rewriting_or_waiting(
    tmp_path: Path, holding_writer
) -> None:
    persist.run_tick(tmp_path, tick_id="legacy-seed", noop=True)
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(store)
    try:
        conn.execute("DROP VIEW latest")
        conn.execute(
            "CREATE VIEW latest AS SELECT seq, tick_id, started_at, duration_ms, "
            "outcome, noop, overlap, last_alert_ok FROM ticks "
            "ORDER BY seq DESC LIMIT 1"
        )
        conn.commit()
        before = conn.execute(
            "SELECT sql FROM sqlite_schema WHERE type='view' AND name='latest'"
        ).fetchone()[0]
    finally:
        conn.close()

    with holding_writer(tmp_path, "legacy-deadman", seconds=8):
        started = time.monotonic()
        verdict = deadman.evaluate_deadman(tmp_path)
        elapsed = time.monotonic() - started

    assert elapsed < 2.0
    assert verdict.reason == "last_alert_unknown"
    conn = sqlite3.connect(store)
    try:
        after = conn.execute(
            "SELECT sql FROM sqlite_schema WHERE type='view' AND name='latest'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert after == before


def test_ensure_view_preserves_error_when_transaction_already_ended(
    tmp_path: Path,
) -> None:
    persist.run_tick(tmp_path, tick_id="legacy-seed", noop=True)
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(store, isolation_level=None)
    try:
        conn.execute("DROP VIEW latest")
        conn.execute(
            "CREATE VIEW latest AS SELECT seq, tick_id, started_at, duration_ms, "
            "outcome, noop, overlap, last_alert_ok FROM ticks "
            "ORDER BY seq DESC LIMIT 1"
        )

        class RolledBackThenFailed:
            @property
            def in_transaction(self) -> bool:
                return conn.in_transaction

            def execute(self, sql: str):
                if sql == db._VIEW_DROP_SQL:
                    conn.execute("ROLLBACK")
                    raise sqlite3.OperationalError("original view replacement error")
                return conn.execute(sql)

        with pytest.raises(
            sqlite3.OperationalError, match="original view replacement error"
        ):
            db._ensure_view(RolledBackThenFailed())
    finally:
        conn.close()
