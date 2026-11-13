"""v1a dead-man: reads the store's latest row."""

from __future__ import annotations

import contextlib
import errno
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import tools.review_orchestrator.deadman as deadman
import tools.review_orchestrator.persist as persist
from tools.review_orchestrator import db

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _plant(
    state_dir: Path,
    tick_id: str,
    started_at: datetime,
    *,
    duration_ms: int | None = None,
    outcome: str = "completed",
    last_alert_ok: int | str | None = None,
) -> None:
    conn = db.connect(state_dir)
    try:
        if last_alert_ok == "":
            conn.execute("PRAGMA ignore_check_constraints = ON")
        if duration_ms is None:
            conn.execute(
                "INSERT INTO ticks "
                "(tick_id, started_at, outcome, overlap, last_alert_ok) "
                "VALUES (?, ?, 'running', 0, ?)",
                (tick_id, started_at.isoformat(), last_alert_ok),
            )
        else:
            conn.execute(
                "INSERT INTO ticks "
                "(tick_id, started_at, duration_ms, outcome, noop, overlap, last_alert_ok) "
                "VALUES (?, ?, ?, ?, 0, 0, ?)",
                (tick_id, started_at.isoformat(), duration_ms, outcome, last_alert_ok),
            )
    finally:
        conn.close()


def test_v1a_tick_without_sender_reports_alert_unknown(tmp_path: Path, capsys) -> None:
    persist.run_tick(tmp_path, tick_id="v1", noop=False)
    row = persist.read_latest_tick(tmp_path)
    assert row is not None
    assert row["tick_id"] == "v1"
    assert row["outcome"] == "completed"
    verdict = deadman.evaluate_deadman(tmp_path)
    assert verdict.ok is False
    assert verdict.reason == "last_alert_unknown"
    assert deadman.main(["--state-dir", str(tmp_path)]) == 1
    assert capsys.readouterr().out.strip() == "last_alert_unknown"


def test_missing_store_unreadable(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    state_dir = tmp_path / "missing-store"
    assert not state_dir.exists()

    verdict = deadman.evaluate_deadman(state_dir, max_age_minutes=40, now=now)
    assert verdict.ok is False
    assert verdict.reason == "heartbeat_unreadable"
    assert not state_dir.exists()


def test_deadman_reads_a_store_created_during_the_check(
    tmp_path: Path, monkeypatch
) -> None:
    state_dir = tmp_path / "created-during-check"
    state_dir.mkdir()
    real_load_latest = deadman._load_latest
    called = False

    def create_before_read(path: Path):
        nonlocal called
        called = True
        persist.run_tick(path, tick_id="created", noop=True)
        return real_load_latest(path)

    monkeypatch.setattr(deadman, "_load_latest", create_before_read)

    verdict = deadman.evaluate_deadman(state_dir)

    assert called
    assert verdict.ok is False
    assert verdict.reason == "last_alert_unknown"


def test_missing_store_cli_does_not_create_state_directory(tmp_path: Path) -> None:
    state_dir = tmp_path / "cli-missing-store"
    result = _run_deadman_cli(state_dir)
    assert result.stdout.strip() == "heartbeat_unreadable"
    assert result.returncode == 1
    assert not state_dir.exists()


def test_missing_store_in_existing_directory_does_not_create_database(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "empty-store"
    state_dir.mkdir()

    verdict = deadman.evaluate_deadman(state_dir)

    assert verdict.ok is False
    assert verdict.reason == "heartbeat_unreadable"
    assert list(state_dir.iterdir()) == []


@pytest.mark.parametrize("duration_ms", ["not-an-integer", "9" * 100])
def test_bad_duration_reports_unreadable_from_deadman_cli(
    tmp_path: Path, duration_ms: str
) -> None:
    _plant(
        tmp_path,
        "bad-duration",
        datetime.now(timezone.utc) - timedelta(minutes=1),
        duration_ms=duration_ms,
    )

    result = _run_deadman_cli(tmp_path)

    assert result.stdout.strip() == "heartbeat_unreadable"
    assert result.returncode == 1


def test_run_tick_creates_missing_state_directory(tmp_path: Path) -> None:
    state_dir = tmp_path / "new-state"
    assert not state_dir.exists()

    result = persist.run_tick(state_dir, tick_id="created", noop=True)

    assert result.seq == 1
    assert db.db_path(state_dir).is_file()


def test_repair_refuses_a_healthy_store(tmp_path: Path) -> None:
    persist.run_tick(tmp_path, tick_id="healthy", noop=True)
    store = db.db_path(tmp_path)

    result = persist.repair_store(tmp_path, stamp="healthy")

    assert result == store
    assert store.is_file()
    assert list(tmp_path.glob("orchestrator.sqlite.corrupt-*")) == []
    assert persist.read_latest_tick(tmp_path)["tick_id"] == "healthy"


def test_repair_moves_store_missing_required_columns(tmp_path: Path) -> None:
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(str(store))
    conn.execute("CREATE TABLE ticks (seq INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    moved = persist.repair_store(tmp_path, stamp="missing-columns")

    assert moved == tmp_path / "orchestrator.sqlite.corrupt-missing-columns"
    assert moved.is_file()
    assert not store.exists()
    assert persist.run_tick(tmp_path, tick_id="recovered", noop=True).seq == 1


@pytest.mark.parametrize(
    ("shape", "seq_declaration", "table_suffix"),
    [
        ("text-primary-key", "TEXT PRIMARY KEY", ""),
        ("integer-primary-key-desc", "INTEGER PRIMARY KEY DESC", ""),
        ("without-rowid", "INTEGER PRIMARY KEY", " WITHOUT ROWID"),
        ("real-primary-key", "REAL PRIMARY KEY", ""),
        ("text-unique", "TEXT UNIQUE", ""),
        ("missing-seq", None, ""),
        ("ticks-view", None, ""),
    ],
)
def test_repair_moves_structurally_untrusted_ticks(
    tmp_path: Path, shape: str, seq_declaration: str | None, table_suffix: str
) -> None:
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(str(store))
    columns = [
        f"seq {seq_declaration}" if seq_declaration is not None else None,
        "tick_id TEXT NOT NULL UNIQUE",
        "started_at TEXT NOT NULL",
        "duration_ms INTEGER",
        "outcome TEXT NOT NULL DEFAULT 'running'",
        "noop INTEGER NOT NULL DEFAULT 0",
        "overlap INTEGER NOT NULL DEFAULT 0",
        "last_alert_ok INTEGER",
    ]
    column_sql = ", ".join(column for column in columns if column is not None)
    if shape == "ticks-view":
        conn.execute(f"CREATE TABLE ticks_source ({column_sql})")
        conn.execute("CREATE VIEW ticks AS SELECT * FROM ticks_source")
    else:
        conn.execute(f"CREATE TABLE ticks ({column_sql}){table_suffix}")
    conn.close()

    moved = persist.repair_store(tmp_path, stamp="bad-seq")

    assert moved == tmp_path / "orchestrator.sqlite.corrupt-bad-seq"
    result = persist.run_tick(tmp_path, tick_id="recovered", noop=True)
    row = persist.read_latest_tick(tmp_path)
    assert result.seq == 1
    assert row is not None
    assert row["seq"] == 1
    assert row["outcome"] == "completed"
    assert row["duration_ms"] is not None


def test_repair_rejects_composite_seq_primary_key_with_matching_row_values(
    tmp_path: Path,
) -> None:
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(str(store))
    conn.execute(
        "CREATE TABLE ticks ("
        "seq INTEGER DEFAULT 2, "
        "tick_id TEXT NOT NULL UNIQUE, "
        "started_at TEXT NOT NULL, "
        "duration_ms INTEGER, "
        "outcome TEXT NOT NULL DEFAULT 'running', "
        "noop INTEGER NOT NULL DEFAULT 0, "
        "overlap INTEGER NOT NULL DEFAULT 0, "
        "last_alert_ok INTEGER, "
        "PRIMARY KEY(seq, tick_id))"
    )
    conn.execute(
        "INSERT INTO ticks(rowid, seq, tick_id, started_at, duration_ms, outcome) "
        "VALUES (1, 1, 'seed', ?, 0, 'completed')",
        (datetime.now(timezone.utc).isoformat(),),
    )
    conn.commit()
    conn.close()

    moved = persist.repair_store(tmp_path, stamp="composite")

    assert moved == tmp_path / "orchestrator.sqlite.corrupt-composite"
    assert moved.is_file()
    assert not store.exists()


def test_repair_rejects_empty_integer_primary_key_desc_with_matching_default(
    tmp_path: Path,
) -> None:
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(str(store))
    conn.execute(
        "CREATE TABLE ticks ("
        "seq INTEGER PRIMARY KEY DESC DEFAULT 1, "
        "tick_id TEXT NOT NULL UNIQUE, "
        "started_at TEXT NOT NULL, "
        "duration_ms INTEGER, "
        "outcome TEXT NOT NULL DEFAULT 'running', "
        "noop INTEGER NOT NULL DEFAULT 0, "
        "overlap INTEGER NOT NULL DEFAULT 0, "
        "last_alert_ok INTEGER)"
    )
    conn.close()

    moved = persist.repair_store(tmp_path, stamp="descending")

    assert moved == tmp_path / "orchestrator.sqlite.corrupt-descending"
    assert moved.is_file()
    assert not store.exists()


def test_repair_keeps_valid_autoincrement_seq_when_rowid_is_shadowed(
    tmp_path: Path,
) -> None:
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(str(store))
    conn.execute(
        "CREATE TABLE ticks ("
        "seq INTEGER PRIMARY KEY AUTOINCREMENT, "
        "rowid TEXT, "
        "tick_id TEXT NOT NULL UNIQUE, "
        "started_at TEXT NOT NULL CHECK (length(started_at) BETWEEN 20 AND 40), "
        "duration_ms INTEGER CHECK "
        "(duration_ms IS NULL OR duration_ms >= 0), "
        "outcome TEXT NOT NULL DEFAULT 'running' CHECK "
        "(outcome IN ('running', 'completed', 'failed', 'abandoned')), "
        "noop INTEGER NOT NULL DEFAULT 0 CHECK (noop IN (0, 1)), "
        "overlap INTEGER NOT NULL DEFAULT 0 CHECK (overlap IN (0, 1)), "
        "last_alert_ok INTEGER CHECK "
        "(last_alert_ok IS NULL OR last_alert_ok IN (0, 1)), "
        "CHECK ((outcome IN ('running', 'abandoned')) = "
        "(duration_ms IS NULL)))"
    )
    conn.execute(
        "INSERT INTO ticks(tick_id, started_at, duration_ms, outcome) "
        "VALUES ('healthy', ?, 0, 'completed')",
        (datetime.now(timezone.utc).isoformat(),),
    )
    conn.commit()
    conn.close()

    result = persist.repair_store(tmp_path, stamp="shadowed-rowid")

    assert result == store
    assert store.is_file()
    assert not (tmp_path / "orchestrator.sqlite.corrupt-shadowed-rowid").exists()
    assert persist.read_latest_tick(tmp_path)["tick_id"] == "healthy"


def test_repair_moves_untrusted_store_with_rollback_trigger(
    tmp_path: Path,
) -> None:
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(str(store))
    conn.execute(
        "CREATE TABLE ticks ("
        "seq INTEGER PRIMARY KEY DESC DEFAULT 1, "
        "tick_id TEXT NOT NULL UNIQUE, "
        "started_at TEXT NOT NULL, "
        "duration_ms INTEGER, "
        "outcome TEXT NOT NULL DEFAULT 'running', "
        "noop INTEGER NOT NULL DEFAULT 0, "
        "overlap INTEGER NOT NULL DEFAULT 0, "
        "last_alert_ok INTEGER)"
    )
    conn.execute(
        "CREATE TRIGGER abort_repair_probe BEFORE INSERT ON ticks "
        "BEGIN SELECT RAISE(ROLLBACK, 'abort repair probe'); END"
    )
    conn.close()

    moved = persist.repair_store(tmp_path, stamp="rollback-trigger")

    assert moved == tmp_path / "orchestrator.sqlite.corrupt-rollback-trigger"
    assert moved.is_file()
    assert not store.exists()


def test_repair_completes_intent_when_absent_sidecars_were_not_listed(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "missing-sidecars"
    persist.run_tick(state_dir, tick_id="seed", noop=True)
    store = db.db_path(state_dir)
    for suffix in ("-wal", "-shm"):
        Path(f"{store}{suffix}").unlink(missing_ok=True)
    moved = state_dir / "orchestrator.sqlite.corrupt-stale"
    db._repair_intent_path(state_dir).write_text(
        json.dumps({"version": 1, "target": moved.name, "files": ["main"]}),
        encoding="utf-8",
    )

    result = persist.repair_store(state_dir, stamp="stale-intent")

    assert result == moved
    assert moved.is_file()
    assert not store.exists()
    assert not db._repair_intent_path(state_dir).exists()


def test_repair_intent_with_missing_main_fails_closed(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "missing-repair-main"
    state_dir.mkdir()
    store = db.db_path(state_dir)
    moved = state_dir / "orchestrator.sqlite.corrupt-missing-main"
    intent = db._repair_intent_path(state_dir)
    intent.write_text(
        json.dumps({"version": 1, "target": moved.name, "files": ["main"]}),
        encoding="utf-8",
    )

    with pytest.raises(db.StoreUnavailableError):
        with db.locked_connect(state_dir):
            pass

    with pytest.raises(db.StoreUnavailableError):
        persist.repair_store(state_dir, stamp="missing-main")

    assert intent.is_file()
    assert not store.exists()
    assert not moved.exists()


def test_repair_intent_rejects_directory_at_pending_main_target(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "directory-repair-main"
    state_dir.mkdir()
    store = db.db_path(state_dir)
    moved = state_dir / "orchestrator.sqlite.corrupt-directory-main"
    moved.mkdir()
    intent = db._repair_intent_path(state_dir)
    intent.write_text(
        json.dumps({"version": 1, "target": moved.name, "files": ["main"]}),
        encoding="utf-8",
    )

    with pytest.raises(db.StoreUnavailableError):
        with db.locked_connect(state_dir):
            pass

    assert intent.is_file()
    assert moved.is_dir()
    assert not store.exists()


def test_repair_cli_reports_target_when_completing_pending_move(
    tmp_path: Path, capsys
) -> None:
    state_dir = tmp_path / "pending-cli-repair"
    persist.run_tick(state_dir, tick_id="seed", noop=True)
    store = db.db_path(state_dir)
    moved = state_dir / "orchestrator.sqlite.corrupt-pending-cli"
    Path(f"{store}-wal").unlink(missing_ok=True)
    Path(f"{store}-shm").unlink(missing_ok=True)
    db._repair_intent_path(state_dir).write_text(
        json.dumps(
            {"version": 1, "target": moved.name, "files": ["main"]}
        ),
        encoding="utf-8",
    )

    assert persist.main(["repair", "--state-dir", str(state_dir)]) == 0

    assert capsys.readouterr().out.strip() == (
        f"repair: moved corrupt store to {moved.name}"
    )
    assert moved.is_file()
    assert not store.exists()
    assert not db._repair_intent_path(state_dir).exists()


def test_repair_accepts_main_already_at_pending_intent_target(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "main-at-target"
    persist.run_tick(state_dir, tick_id="seed", noop=True)
    store = db.db_path(state_dir)
    moved = state_dir / "orchestrator.sqlite.corrupt-main-at-target"
    Path(f"{store}-wal").unlink(missing_ok=True)
    Path(f"{store}-shm").unlink(missing_ok=True)
    store.replace(moved)
    db._repair_intent_path(state_dir).write_text(
        json.dumps({"version": 1, "target": moved.name, "files": ["main"]}),
        encoding="utf-8",
    )

    result = persist.repair_store(state_dir, stamp="main-at-target")

    assert result == moved
    assert moved.is_file()
    assert not store.exists()
    assert not db._repair_intent_path(state_dir).exists()


def test_repair_quarantines_store_with_trigger_attached_to_ticks(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "ticks-trigger"
    persist.run_tick(state_dir, tick_id="seed", noop=True)
    store = db.db_path(state_dir)
    conn = sqlite3.connect(str(store))
    try:
        conn.execute(
            "CREATE TRIGGER delete_ticks_after_insert AFTER INSERT ON ticks "
            "BEGIN DELETE FROM ticks; END"
        )
    finally:
        conn.close()

    moved = persist.repair_store(state_dir, stamp="ticks-trigger")

    assert moved == state_dir / "orchestrator.sqlite.corrupt-ticks-trigger"
    assert moved.is_file()
    assert not store.exists()


def test_repair_keeps_store_with_trigger_named_ticks_on_another_table(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "other-table-trigger"
    persist.run_tick(state_dir, tick_id="seed", noop=True)
    store = db.db_path(state_dir)
    conn = sqlite3.connect(str(store))
    try:
        conn.execute("CREATE TABLE other_table (value TEXT)")
        conn.execute(
            "CREATE TRIGGER ticks AFTER INSERT ON other_table "
            "BEGIN SELECT 1; END"
        )
    finally:
        conn.close()

    result = persist.repair_store(state_dir, stamp="other-table-trigger")

    assert result == store
    assert store.is_file()
    assert not (
        state_dir / "orchestrator.sqlite.corrupt-other-table-trigger"
    ).exists()
    assert persist.read_latest_tick(state_dir)["tick_id"] == "seed"


def test_repair_keeps_case_folded_ticks_schema(tmp_path: Path) -> None:
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(str(store))
    try:
        conn.execute(
            "CREATE TABLE TICKS ("
            "SEQ INTEGER PRIMARY KEY AUTOINCREMENT, "
            "TICK_ID TEXT NOT NULL UNIQUE, "
            "STARTED_AT TEXT NOT NULL CHECK "
            "(length(STARTED_AT) BETWEEN 20 AND 40), "
            "DURATION_MS INTEGER CHECK "
            "(DURATION_MS IS NULL OR DURATION_MS >= 0), "
            "OUTCOME TEXT NOT NULL DEFAULT 'running' CHECK "
            "(OUTCOME IN ('running', 'completed', 'failed', 'abandoned')), "
            "NOOP INTEGER NOT NULL DEFAULT 0 CHECK (NOOP IN (0, 1)), "
            "OVERLAP INTEGER NOT NULL DEFAULT 0 CHECK (OVERLAP IN (0, 1)), "
            "LAST_ALERT_OK INTEGER CHECK "
            "(LAST_ALERT_OK IS NULL OR LAST_ALERT_OK IN (0, 1)), "
            "CHECK ((OUTCOME IN ('running', 'abandoned')) = "
            "(DURATION_MS IS NULL)))"
        )
        conn.execute(
            "INSERT INTO TICKS "
            "(TICK_ID, STARTED_AT, DURATION_MS, OUTCOME) "
            "VALUES ('seed', ?, 0, 'completed')",
            (datetime.now(timezone.utc).isoformat(),),
        )
        conn.commit()
    finally:
        conn.close()

    result = persist.repair_store(tmp_path, stamp="case-folded")

    assert result == store
    assert store.is_file()
    assert not (tmp_path / "orchestrator.sqlite.corrupt-case-folded").exists()
    assert persist.run_tick(tmp_path, tick_id="next", noop=True).seq == 2
    assert persist.read_latest_tick(tmp_path)["tick_id"] == "next"


@pytest.mark.parametrize(
    "shape",
    [
        "poisoned-sqlite-sequence",
        "missing-unique-tick-id",
        "missing-autoincrement",
        "impostor-latest-table",
    ],
)
def test_repair_quarantines_writer_unusable_store_shapes(
    tmp_path: Path, shape: str
) -> None:
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(str(store))
    try:
        if shape == "poisoned-sqlite-sequence":
            conn.execute(db._TABLE_SQL)
            conn.execute(
                "INSERT INTO ticks "
                "(tick_id, started_at, duration_ms, outcome) "
                "VALUES ('seed', ?, 0, 'completed')",
                (datetime.now(timezone.utc).isoformat(),),
            )
            conn.execute(
                "UPDATE sqlite_sequence SET seq = ? WHERE name = 'ticks'",
                (db.MAX_TRUSTED_SEQ + 1,),
            )
        else:
            seq_declaration = (
                "INTEGER PRIMARY KEY"
                if shape == "missing-autoincrement"
                else "INTEGER PRIMARY KEY AUTOINCREMENT"
            )
            tick_id_declaration = (
                "TEXT NOT NULL"
                if shape == "missing-unique-tick-id"
                else "TEXT NOT NULL UNIQUE"
            )
            conn.execute(
                "CREATE TABLE ticks ("
                f"seq {seq_declaration}, "
                f"tick_id {tick_id_declaration}, "
                "started_at TEXT NOT NULL, "
                "duration_ms INTEGER, "
                "outcome TEXT NOT NULL DEFAULT 'running', "
                "noop INTEGER NOT NULL DEFAULT 0, "
                "overlap INTEGER NOT NULL DEFAULT 0, "
                "last_alert_ok INTEGER)"
            )
            if shape == "impostor-latest-table":
                conn.execute("CREATE TABLE latest (value TEXT)")
            else:
                conn.execute(db._VIEW_SQL)
        conn.commit()
    finally:
        conn.close()

    moved = persist.repair_store(tmp_path, stamp=shape)

    assert moved == tmp_path / f"orchestrator.sqlite.corrupt-{shape}"
    assert moved.is_file()
    assert not store.exists()
    assert persist.run_tick(tmp_path, tick_id="recovered", noop=True).seq == 1


def test_locked_connect_times_out_when_store_lock_is_contended(
    tmp_path: Path, monkeypatch
) -> None:
    state_dir = tmp_path / "contended-lock"
    state_dir.mkdir()
    monkeypatch.setattr(db, "STORE_LOCK_TIMEOUT_SECONDS", 0.1, raising=False)
    holder = os.open(state_dir, os.O_RDONLY)
    db.fcntl.flock(holder, db.fcntl.LOCK_EX)
    errors: list[BaseException] = []
    finished = threading.Event()

    def open_store() -> None:
        try:
            with db.locked_connect(state_dir):
                pass
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()

    worker = threading.Thread(target=open_store, daemon=True)
    started = time.monotonic()
    try:
        worker.start()
        finished_while_contended = finished.wait(timeout=0.5)
    finally:
        db.fcntl.flock(holder, db.fcntl.LOCK_UN)
        os.close(holder)
    worker.join(timeout=1)

    assert finished_while_contended
    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], db.StoreUnavailableError)
    assert "timed out acquiring store lock" in str(errors[0])
    assert time.monotonic() - started < 0.5
    assert not db.db_path(state_dir).exists()


def test_repair_moves_untrusted_store_past_ambiguous_repair_intent(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "ambiguous-intent"
    state_dir.mkdir()
    store = db.db_path(state_dir)
    conn = sqlite3.connect(str(store))
    conn.execute(
        "CREATE TABLE ticks ("
        "seq INTEGER PRIMARY KEY DESC DEFAULT 1, "
        "tick_id TEXT NOT NULL UNIQUE, "
        "started_at TEXT NOT NULL, "
        "duration_ms INTEGER, "
        "outcome TEXT NOT NULL DEFAULT 'running', "
        "noop INTEGER NOT NULL DEFAULT 0, "
        "overlap INTEGER NOT NULL DEFAULT 0, "
        "last_alert_ok INTEGER)"
    )
    conn.close()
    old_target = state_dir / "orchestrator.sqlite.corrupt-after-ambiguous"
    shutil.copy2(store, old_target)
    db._repair_intent_path(state_dir).write_text(
        json.dumps({"version": 1, "target": old_target.name, "files": ["main"]}),
        encoding="utf-8",
    )

    moved = persist.repair_store(state_dir, stamp="after-ambiguous")

    assert moved != old_target
    assert moved.name.startswith("orchestrator.sqlite.corrupt-after-ambiguous-")
    assert moved.is_file()
    assert old_target.is_file()
    assert not store.exists()
    assert not db._repair_intent_path(state_dir).exists()
    assert len(list(state_dir.glob(".orchestrator-repair-intent.json.orphan-*"))) == 1


def test_repair_moves_untrusted_store_past_corrupt_repair_intent(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "corrupt-intent"
    state_dir.mkdir()
    store = db.db_path(state_dir)
    conn = sqlite3.connect(str(store))
    conn.execute(
        "CREATE TABLE ticks ("
        "seq INTEGER PRIMARY KEY DESC DEFAULT 1, "
        "tick_id TEXT NOT NULL UNIQUE, "
        "started_at TEXT NOT NULL, "
        "duration_ms INTEGER, "
        "outcome TEXT NOT NULL DEFAULT 'running', "
        "noop INTEGER NOT NULL DEFAULT 0, "
        "overlap INTEGER NOT NULL DEFAULT 0, "
        "last_alert_ok INTEGER)"
    )
    conn.close()
    db._repair_intent_path(state_dir).write_text(
        "{\"version\":1,\"target\":",
        encoding="utf-8",
    )

    moved = persist.repair_store(state_dir, stamp="after-corrupt-intent")

    assert moved == state_dir / "orchestrator.sqlite.corrupt-after-corrupt-intent"
    assert moved.is_file()
    assert not store.exists()
    assert not db._repair_intent_path(state_dir).exists()
    assert len(list(state_dir.glob(".orchestrator-repair-intent.json.orphan-*"))) == 1


def test_repair_cli_reports_healthy_store_as_unchanged(
    tmp_path: Path, capsys
) -> None:
    persist.run_tick(tmp_path, tick_id="healthy", noop=True)

    assert persist.main(["repair", "--state-dir", str(tmp_path)]) == 0

    assert capsys.readouterr().out.strip() == "repair: healthy store; nothing moved"


def test_repair_moves_wal_sidecars_and_preserves_committed_rows(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "repair"
    persist.run_tick(state_dir, tick_id="seed", noop=True)
    store = db.db_path(state_dir)
    wal_keeper = sqlite3.connect(str(store), isolation_level=None)
    wal_keeper.execute("PRAGMA wal_autocheckpoint = 0")
    wal_keeper.execute(
        "INSERT INTO ticks "
        "(seq, tick_id, started_at, duration_ms, outcome, noop, overlap) "
        "VALUES (?, 'wal-only-corruption', ?, 0, 'completed', 0, 0)",
        (db.MAX_TRUSTED_SEQ + 1, datetime.now(timezone.utc).isoformat()),
    )
    wal_path = Path(f"{store}-wal")
    assert wal_path.is_file()
    assert wal_path.stat().st_size > 0
    immutable = sqlite3.connect(f"{store.as_uri()}?immutable=1", uri=True)
    try:
        assert immutable.execute(
            "SELECT COUNT(*) FROM ticks WHERE tick_id = 'wal-only-corruption'"
        ).fetchone()[0] == 0
    finally:
        immutable.close()

    moved = persist.repair_store(state_dir, stamp="wal")

    assert moved == state_dir / "orchestrator.sqlite.corrupt-wal"
    assert Path(f"{moved}-wal").is_file()
    assert Path(f"{moved}-shm").is_file()
    assert not store.exists()
    assert not wal_path.exists()
    assert not Path(f"{store}-shm").exists()
    wal_keeper.close()

    moved_conn = sqlite3.connect(str(moved))
    try:
        moved_ids = {
            row[0] for row in moved_conn.execute("SELECT tick_id FROM ticks")
        }
    finally:
        moved_conn.close()
    assert {"seed", "wal-only-corruption"} <= moved_ids

    fresh = persist.run_tick(state_dir, tick_id="fresh", noop=True)
    assert fresh.seq == 1
    fresh_conn = sqlite3.connect(str(store))
    try:
        assert fresh_conn.execute(
            "SELECT seq, tick_id FROM ticks"
        ).fetchall() == [(1, "fresh")]
    finally:
        fresh_conn.close()


def test_repair_waits_for_live_tick_before_checking_store(tmp_path: Path) -> None:
    state_dir = tmp_path / "active-tick"
    persist.run_tick(state_dir, tick_id="seed", noop=True)
    tick_started = threading.Event()
    finish_tick = threading.Event()
    tick_errors: list[BaseException] = []

    def work() -> None:
        tick_started.set()
        if not finish_tick.wait(timeout=5):
            raise TimeoutError("test did not release the tick")

    def run_tick() -> None:
        try:
            persist.run_tick(state_dir, tick_id="live", work=work)
        except BaseException as exc:
            tick_errors.append(exc)

    tick_thread = threading.Thread(target=run_tick)
    tick_thread.start()
    assert tick_started.wait(timeout=3)
    repair_done = threading.Event()
    repair_result: dict[str, Path] = {}
    repair_errors: list[BaseException] = []

    def repair() -> None:
        try:
            repair_result["path"] = persist.repair_store(state_dir, stamp="active")
        except BaseException as exc:
            repair_errors.append(exc)
        finally:
            repair_done.set()

    repair_thread = threading.Thread(target=repair)
    repair_thread.start()
    waited_for_tick = not repair_done.wait(timeout=0.1)
    finish_tick.set()
    tick_thread.join(timeout=3)
    repair_thread.join(timeout=3)

    assert waited_for_tick
    assert not tick_thread.is_alive()
    assert not repair_thread.is_alive()
    assert not tick_errors
    assert not repair_errors
    assert repair_result["path"] == db.db_path(state_dir)
    row = persist.read_latest_tick(state_dir)
    assert row is not None
    assert row["tick_id"] == "live"
    assert row["outcome"] == "completed"


@pytest.mark.parametrize("crash_after", ["main", "wal", "shm"])
def test_repair_recovers_after_each_file_rename(
    tmp_path: Path, monkeypatch, crash_after: str
) -> None:
    class SimulatedCrash(BaseException):
        pass

    state_dir = tmp_path / crash_after
    persist.run_tick(state_dir, tick_id="seed", noop=True)
    store = db.db_path(state_dir)
    wal_keeper = sqlite3.connect(str(store), isolation_level=None)
    wal_keeper.execute("PRAGMA wal_autocheckpoint = 0")
    wal_keeper.execute(
        "INSERT INTO ticks "
        "(seq, tick_id, started_at, duration_ms, outcome, noop, overlap) "
        "VALUES (?, 'wal-only-crash-row', ?, 0, 'completed', 0, 0)",
        (db.MAX_TRUSTED_SEQ + 1, datetime.now(timezone.utc).isoformat()),
    )

    real_replace = Path.replace

    def interrupt_after_rename(source: Path, target: Path) -> Path:
        result = real_replace(source, target)
        renamed = (
            "main"
            if source == store
            else "wal"
            if source == Path(f"{store}-wal")
            else "shm"
            if source == Path(f"{store}-shm")
            else None
        )
        if renamed == crash_after:
            raise SimulatedCrash(crash_after)
        return result

    monkeypatch.setattr(Path, "replace", interrupt_after_rename)
    with pytest.raises(SimulatedCrash, match=crash_after):
        persist.repair_store(state_dir, stamp="interrupted")
    monkeypatch.setattr(Path, "replace", real_replace)

    fresh = persist.run_tick(state_dir, tick_id="fresh", noop=True)
    assert fresh.seq == 1
    moved = state_dir / "orchestrator.sqlite.corrupt-interrupted"
    assert moved.is_file()
    assert Path(f"{moved}-wal").is_file()
    assert Path(f"{moved}-shm").is_file()
    wal_keeper.close()

    moved_conn = sqlite3.connect(str(moved))
    try:
        moved_ids = {
            row[0] for row in moved_conn.execute("SELECT tick_id FROM ticks")
        }
    finally:
        moved_conn.close()
    assert {"seed", "wal-only-crash-row"} <= moved_ids

    fresh_row = persist.read_latest_tick(state_dir)
    assert fresh_row is not None
    assert fresh_row["seq"] == 1
    assert fresh_row["tick_id"] == "fresh"
    assert fresh_row["outcome"] == "completed"


def test_fresh_completed_row_ok(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant(
        tmp_path,
        "hb",
        now - timedelta(minutes=1),
        duration_ms=1000,
        last_alert_ok=1,
    )
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is True
    assert verdict.reason == "ok"


def test_running_row_past_limit_attempt_stale(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant(tmp_path, "hb", now - timedelta(minutes=41))
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.reason == "attempt_stale"


def test_abandoned_row_attempt_stale(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    old = (now - timedelta(minutes=41)).isoformat()
    conn = db.connect(tmp_path)
    try:
        conn.execute(
            "INSERT INTO ticks (tick_id, started_at, outcome, overlap) "
            "VALUES ('killed', ?, 'abandoned', 0)",
            (old,),
        )
    finally:
        conn.close()
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.reason == "attempt_stale"


def test_completed_stale_41m(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant(tmp_path, "hb", now - timedelta(minutes=41), duration_ms=0)
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.reason == "completed_stale"


def test_completed_uses_completion_not_start(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant(
        tmp_path,
        "hb",
        now - timedelta(minutes=80),
        duration_ms=79 * 60 * 1000,
        last_alert_ok=1,
    )
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is True


def test_future_started_at_alerts(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant(tmp_path, "hb", now + timedelta(minutes=6))
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.reason == "heartbeat_future"


def test_future_completed_at_alerts(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant(tmp_path, "hb", now - timedelta(minutes=1), duration_ms=7 * 60 * 1000)
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.reason == "heartbeat_future"


@pytest.mark.parametrize(
    ("offset", "expect_future"),
    [
        (timedelta(minutes=5), False),
        (timedelta(minutes=5, seconds=1), True),
    ],
)
def test_future_slack_boundary_on_started_at(
    tmp_path: Path, offset: timedelta, expect_future: bool
) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant(tmp_path, "hb", now + offset, duration_ms=0, last_alert_ok=1)
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    if expect_future:
        assert verdict.reason == "heartbeat_future"
    else:
        assert verdict.ok is True


@pytest.mark.parametrize(
    ("kind", "age_seconds", "expect_ok"),
    [
        ("running", 40 * 60 - 1, True),
        ("running", 40 * 60, True),
        ("running", 40 * 60 + 1, False),
        ("completed", 40 * 60 - 1, True),
        ("completed", 40 * 60, True),
        ("completed", 40 * 60 + 1, False),
    ],
)
def test_age_boundary_seconds(
    tmp_path: Path, kind: str, age_seconds: int, expect_ok: bool
) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    started = now - timedelta(seconds=age_seconds)
    _plant(
        tmp_path,
        "hb",
        started,
        duration_ms=0 if kind == "completed" else None,
        last_alert_ok=1,
    )
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is expect_ok


def test_last_alert_failed_alerts(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant(
        tmp_path,
        "hb",
        now - timedelta(minutes=1),
        duration_ms=0,
        last_alert_ok=0,
    )
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.reason == "last_alert_failed"


def test_last_alert_ok_true_is_ok(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant(
        tmp_path,
        "hb",
        now - timedelta(minutes=1),
        duration_ms=0,
        last_alert_ok=1,
    )
    assert deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now).ok is True


@pytest.mark.parametrize("last_alert_ok", [None, ""])
def test_unknown_last_alert_status_is_not_healthy(
    tmp_path: Path, last_alert_ok: int | str | None
) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant(
        tmp_path,
        "unknown-alert",
        now - timedelta(minutes=1),
        duration_ms=0,
        last_alert_ok=last_alert_ok,
    )

    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)

    assert verdict.ok is False
    assert verdict.reason == "last_alert_unknown"


def test_corrupt_store_unreadable_not_crash(tmp_path: Path) -> None:
    db.db_path(tmp_path).write_text("not a database", encoding="utf-8")
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is False
    assert verdict.reason == "heartbeat_unreadable"


def _require_unprivileged() -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root bypasses directory permissions")


@contextlib.contextmanager
def _read_only(path: Path):
    """Make a directory unwritable for the body, then restore it for cleanup."""
    mode = path.stat().st_mode
    os.chmod(path, 0o555)
    try:
        yield path
    finally:
        os.chmod(path, mode)


def _run_deadman_cli(state_dir: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.review_orchestrator.deadman",
            "--state-dir",
            str(state_dir),
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
        check=False,
    )


def test_read_only_store_reports_unreadable_end_to_end(tmp_path: Path) -> None:
    """A store the reader cannot open is an alert, not a dead-man error.

    The reader needs write access to the state directory for the WAL wal-index
    (`-shm`), so an unwritable store is reachable in production. The README
    promises heartbeat_unreadable and exit 1 for it; deadman_error and exit 3
    would only reach the log, and the watchdog would never alert.
    """
    _require_unprivileged()
    state = tmp_path / "store"
    state.mkdir()
    persist.run_tick(state, tick_id="seeded", noop=True)

    with _read_only(state):
        result = _run_deadman_cli(state)

    assert result.stdout.strip() == "heartbeat_unreadable"
    assert result.returncode == 1


@pytest.mark.parametrize(
    "error",
    [
        db.StoreCorruptError("not a database"),
        db.StoreUnavailableError("read-only directory"),
        sqlite3.OperationalError("database is locked"),
        OSError(errno.EROFS, "Read-only file system"),
    ],
)
def test_every_store_open_failure_is_heartbeat_unreadable(
    tmp_path: Path, monkeypatch, capsys, error: BaseException
) -> None:
    """Every way the store can refuse to open is one alert reason."""

    persist.run_tick(tmp_path, tick_id="seed", noop=True)
    called = False

    def boom(*_args, **_kwargs):
        nonlocal called
        called = True
        raise error

    monkeypatch.setattr(deadman.db, "connect_reader", boom, raising=False)
    code = deadman.main(["--state-dir", str(tmp_path)])
    assert called
    assert code == 1
    assert capsys.readouterr().out.strip() == "heartbeat_unreadable"


def test_reader_sees_newest_by_seq_not_completion_order(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant(tmp_path, "early", now - timedelta(minutes=5), duration_ms=0)
    # A later tick that started later but reported first still owns the newest seq.
    _plant(tmp_path, "late", now - timedelta(minutes=1), last_alert_ok=1)
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is True
    assert persist.read_latest_tick(tmp_path)["tick_id"] == "late"


def test_second_process_reader_sees_committed_state(tmp_path: Path) -> None:
    persist.run_tick(tmp_path, tick_id="committed", noop=True)
    assert _run_reader(tmp_path) == "last_alert_unknown"


def test_second_process_reader_reports_stale(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    _plant(tmp_path, "stuck", now - timedelta(minutes=41))
    assert _run_reader(tmp_path, max_age_minutes=40) == "attempt_stale"


def _run_reader(state_dir: Path, *, max_age_minutes: int = 40) -> str:
    code = (
        "from pathlib import Path\n"
        "from tools.review_orchestrator.deadman import evaluate_deadman\n"
        f"print(evaluate_deadman(Path({str(state_dir)!r}), "
        f"max_age_minutes={max_age_minutes}).reason)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
        check=True,
    )
    return out.stdout.strip()


def test_library_default_max_age_is_40(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant(tmp_path, "hb", now - timedelta(minutes=41))
    assert deadman.evaluate_deadman(tmp_path, now=now).reason == "attempt_stale"


def test_cli_ok_exit_and_reason(tmp_path: Path, capsys) -> None:
    _plant(
        tmp_path,
        "cli",
        datetime.now(timezone.utc),
        duration_ms=0,
        last_alert_ok=1,
    )
    code = deadman.main(["--state-dir", str(tmp_path)])
    assert code == 0
    assert capsys.readouterr().out.strip() == "ok"


def test_cli_default_max_age_40(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    _plant(tmp_path, "hb", now - timedelta(minutes=41))
    assert deadman.main(["--state-dir", str(tmp_path)]) == 1


def test_cli_unexpected_error_exit_3(tmp_path: Path, monkeypatch, capsys) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("simulated")

    monkeypatch.setattr(deadman, "evaluate_deadman", boom)
    code = deadman.main(["--state-dir", str(tmp_path)])
    assert code == 3
    assert capsys.readouterr().out.strip() == "deadman_error:RuntimeError"


def test_mutation_reader_treating_running_as_completed_misreports(
    tmp_path: Path, monkeypatch
) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant(tmp_path, "stuck", now - timedelta(minutes=41))
    real = deadman._derived_completed_at

    def always_completed(started_at, duration_ms):
        return started_at + timedelta(milliseconds=int(duration_ms or 0))

    monkeypatch.setattr(deadman, "_derived_completed_at", always_completed)
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.reason == "completed_stale"

    monkeypatch.setattr(deadman, "_derived_completed_at", real)
    fixed = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert fixed.reason == "attempt_stale"


def test_finished_failed_tick_alerts(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant(
        tmp_path,
        "failing",
        now - timedelta(minutes=1),
        duration_ms=5,
        outcome="failed",
        last_alert_ok=1,
    )
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is False
    assert verdict.reason == "tick_failed"


def test_running_row_defers_tick_failed(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant(
        tmp_path, "failed", now - timedelta(minutes=3), duration_ms=5, outcome="failed"
    )
    _plant(tmp_path, "retry", now - timedelta(minutes=1), last_alert_ok=1)
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.ok is True
    assert verdict.reason == "ok"


@pytest.mark.parametrize(
    ("age_seconds", "expected"),
    [(40 * 60, "tick_failed"), (40 * 60 + 1, "completed_stale")],
)
def test_staleness_outranks_tick_failed(
    tmp_path: Path, age_seconds: int, expected: str
) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant(
        tmp_path,
        "failing",
        now - timedelta(seconds=age_seconds),
        duration_ms=0,
        outcome="failed",
    )
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.reason == expected


def test_tick_failed_outranks_last_alert_failed(tmp_path: Path) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant(
        tmp_path,
        "failing",
        now - timedelta(minutes=1),
        duration_ms=5,
        outcome="failed",
        last_alert_ok=0,
    )
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert verdict.reason == "tick_failed"


def test_mutation_reader_ignoring_failed_outcome_misreports(
    tmp_path: Path, monkeypatch
) -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    _plant(
        tmp_path,
        "failing",
        now - timedelta(minutes=1),
        duration_ms=5,
        outcome="failed",
        last_alert_ok=1,
    )
    monkeypatch.setattr(deadman, "_is_failed", lambda _row: False)
    broken = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert broken.ok is True

    monkeypatch.undo()
    fixed = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=now)
    assert fixed.reason == "tick_failed"


# --- reads during a live writer, and clock steps -------------------------


def _rows(state_dir: Path) -> list[dict]:
    conn = db.connect(state_dir)
    try:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT seq, tick_id, started_at, duration_ms, outcome, noop, overlap "
                "FROM ticks ORDER BY seq"
            )
        ]
    finally:
        conn.close()


def test_deadman_read_while_a_writer_holds_the_lock_returns_at_once(
    tmp_path: Path, holding_writer
) -> None:
    persist.run_tick(tmp_path, tick_id="committed", noop=True)
    with holding_writer(tmp_path, "holder", seconds=3):
        started = time.monotonic()
        verdict = deadman.evaluate_deadman(tmp_path)
        elapsed = time.monotonic() - started
    assert verdict.ok is False
    assert verdict.reason == "last_alert_unknown"
    # The reader must not wait out the writer's busy timeout.
    assert elapsed < 2.0


def test_reader_sees_only_committed_rows(tmp_path: Path, holding_writer) -> None:
    persist.run_tick(tmp_path, tick_id="committed", noop=True)
    with holding_writer(tmp_path, "in-flight", seconds=3):
        assert {row["tick_id"] for row in _rows(tmp_path)} == {"committed"}


def test_forward_clock_step_still_reads_the_newest_seq(
    tmp_path: Path, monkeypatch
) -> None:
    base = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(persist, "utc_now", lambda: base)
    persist.run_tick(tmp_path, tick_id="first", noop=True)
    monkeypatch.setattr(persist, "utc_now", lambda: base + timedelta(hours=1))
    persist.run_tick(tmp_path, tick_id="second", noop=True)

    assert persist.read_latest_tick(tmp_path)["tick_id"] == "second"
    verdict = deadman.evaluate_deadman(
        tmp_path, max_age_minutes=40, now=base + timedelta(hours=1)
    )
    assert verdict.ok is False
    assert verdict.reason == "last_alert_unknown"


# --- round-4 review fixes (Replit + Ditto Claude on 7bf4a3d6) ---------------


def _create_ticks_schema(conn: sqlite3.Connection, sql: str) -> None:
    conn.execute(sql)
    conn.commit()


def test_repair_keeps_schema_with_leading_comment_and_quoted_identifiers(
    tmp_path: Path,
) -> None:
    """A canonical schema wrapped in comments and single-quoted names is healthy.

    The structural lexer this replaces parsed neither a leading comment before
    CREATE TABLE nor single-quoted identifiers, so both were quarantined.
    """
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(str(store))
    try:
        _create_ticks_schema(
            conn,
            "/* reviewed (2026-08-19); canonical shape */\n"
            "-- autoincrement, one row per tick\n"
            "CREATE TABLE 'ticks' (\n"
            "    'seq' INTEGER PRIMARY KEY AUTOINCREMENT,\n"
            "    'tick_id' TEXT NOT NULL UNIQUE,\n"
                "    'started_at' TEXT NOT NULL CHECK "
                "(length(started_at) BETWEEN 20 AND 40),\n"
                "    'duration_ms' INTEGER CHECK "
                "(duration_ms IS NULL OR duration_ms >= 0),\n"
                "    'outcome' TEXT NOT NULL DEFAULT 'running' CHECK "
                "(outcome IN ('running', 'completed', 'failed', 'abandoned')),\n"
                "    'noop' INTEGER NOT NULL DEFAULT 0 CHECK (noop IN (0, 1)),\n"
                "    'overlap' INTEGER NOT NULL DEFAULT 0 CHECK (overlap IN (0, 1)),\n"
                "    'last_alert_ok' INTEGER CHECK "
                "(last_alert_ok IS NULL OR last_alert_ok IN (0, 1)),\n"
                "    CHECK ((outcome IN ('running', 'abandoned')) = "
                "(duration_ms IS NULL))\n"
            ")"
        )
    finally:
        conn.close()

    result = persist.repair_store(tmp_path, stamp="quoted-commented")

    assert result == store
    assert not (tmp_path / "orchestrator.sqlite.corrupt-quoted-commented").exists()
    assert persist.run_tick(tmp_path, tick_id="next", noop=True).seq == 1


def test_repair_quarantines_uppercase_ticks_with_trigger_on_ticks(
    tmp_path: Path,
) -> None:
    """A trigger target is matched case-insensitively without executing it."""
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(str(store))
    try:
        _create_ticks_schema(
            conn,
            "CREATE TABLE TICKS ("
            "SEQ INTEGER PRIMARY KEY AUTOINCREMENT, "
            "TICK_ID TEXT NOT NULL UNIQUE, "
            "STARTED_AT TEXT NOT NULL, "
            "DURATION_MS INTEGER, "
            "OUTCOME TEXT NOT NULL DEFAULT 'running', "
            "NOOP INTEGER NOT NULL DEFAULT 0, "
            "OVERLAP INTEGER NOT NULL DEFAULT 0, "
            "LAST_ALERT_OK INTEGER)"
        )
        conn.execute(
            "CREATE TRIGGER abort_probe BEFORE INSERT ON TICKS "
            "BEGIN SELECT RAISE(ROLLBACK, 'abort probe'); END"
        )
    finally:
        conn.close()

    moved = persist.repair_store(tmp_path, stamp="uppercase-trigger")

    assert moved == tmp_path / "orchestrator.sqlite.corrupt-uppercase-trigger"
    assert moved.is_file()
    assert not store.exists()


@pytest.mark.parametrize(
    "hostile_column",
    [
        "started_at TEXT NOT NULL CHECK (length(started_at) > 0 AND 0)",
        "started_at TEXT NOT NULL CHECK (0)",
    ],
)
def test_repair_quarantines_hostile_check_constraint(
    tmp_path: Path, hostile_column: str
) -> None:
    """Unknown CHECK expressions are rejected by the schema allowlist."""
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(str(store))
    try:
        _create_ticks_schema(
            conn,
            "CREATE TABLE ticks ("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, "
            "tick_id TEXT NOT NULL UNIQUE, "
            f"{hostile_column}, "
            "duration_ms INTEGER, "
            "outcome TEXT NOT NULL DEFAULT 'running', "
            "noop INTEGER NOT NULL DEFAULT 0, "
            "overlap INTEGER NOT NULL DEFAULT 0, "
            "last_alert_ok INTEGER)"
        )
    finally:
        conn.close()

    moved = persist.repair_store(tmp_path, stamp="hostile-check")

    assert moved == tmp_path / "orchestrator.sqlite.corrupt-hostile-check"
    assert moved.is_file()
    assert persist.run_tick(tmp_path, tick_id="recovered", noop=True).seq == 1


def test_repair_quarantines_extra_not_null_column(tmp_path: Path) -> None:
    """A column the writer never fills with NOT NULL and no default is untrusted."""
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(str(store))
    try:
        _create_ticks_schema(
            conn,
            "CREATE TABLE ticks ("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, "
            "tick_id TEXT NOT NULL UNIQUE, "
            "started_at TEXT NOT NULL, "
            "duration_ms INTEGER, "
            "outcome TEXT NOT NULL DEFAULT 'running', "
            "noop INTEGER NOT NULL DEFAULT 0, "
            "overlap INTEGER NOT NULL DEFAULT 0, "
            "last_alert_ok INTEGER, "
            "shard TEXT NOT NULL)"
        )
    finally:
        conn.close()

    moved = persist.repair_store(tmp_path, stamp="extra-not-null")

    assert moved == tmp_path / "orchestrator.sqlite.corrupt-extra-not-null"
    assert moved.is_file()
    assert persist.run_tick(tmp_path, tick_id="recovered", noop=True).seq == 1


def test_repair_schema_check_leaves_no_rows_or_sequence_change(
    tmp_path: Path,
) -> None:
    """Read-only validation leaves rows, sqlite_sequence, and next seq unchanged."""
    persist.run_tick(tmp_path, tick_id="first", noop=True)
    conn = sqlite3.connect(str(db.db_path(tmp_path)))
    try:
        before_rows = conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
        before_sequence = conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'ticks'"
        ).fetchone()[0]
    finally:
        conn.close()

    result = persist.repair_store(tmp_path, stamp="schema-validation")
    assert result == db.db_path(tmp_path)

    conn = sqlite3.connect(str(db.db_path(tmp_path)))
    try:
        assert conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0] == before_rows
        assert (
            conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'ticks'").fetchone()[0]
            == before_sequence
        )
    finally:
        conn.close()
    assert persist.run_tick(tmp_path, tick_id="second", noop=True).seq == 2


def test_repair_intent_rejects_symlink_at_pending_main_target(
    tmp_path: Path,
) -> None:
    """`is_file()` follows a symlink, so a symlink at the pending main target
    looked like a completed move. lstat keeps it a non-regular file: fail closed."""
    state_dir = tmp_path / "symlink-repair-main"
    state_dir.mkdir()
    decoy = state_dir / "decoy.sqlite"
    conn = sqlite3.connect(str(decoy))
    try:
        conn.execute("CREATE TABLE ticks (seq INTEGER PRIMARY KEY AUTOINCREMENT)")
        conn.commit()
    finally:
        conn.close()
    # Only the pending target exists, and it is a symlink: `is_file()` follows it
    # and reports a completed move, so the intent is unlinked and the symlink is
    # accepted as the repaired store.
    moved = state_dir / "orchestrator.sqlite.corrupt-symlink"
    moved.symlink_to(decoy)
    intent = db._repair_intent_path(state_dir)
    intent.write_text(
        json.dumps({"version": 1, "target": moved.name, "files": ["main"]}),
        encoding="utf-8",
    )

    with pytest.raises(db.StoreUnavailableError):
        with db.locked_connect(state_dir):
            pass

    assert intent.is_file()
    assert moved.is_symlink()
    assert not db.db_path(state_dir).exists()


def test_repair_intent_rejects_symlink_at_source_main(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "symlink-source-main"
    state_dir.mkdir()
    decoy = state_dir / "decoy.sqlite"
    conn = sqlite3.connect(str(decoy))
    try:
        conn.execute("CREATE TABLE ticks (seq INTEGER PRIMARY KEY AUTOINCREMENT)")
        conn.commit()
    finally:
        conn.close()
    store = db.db_path(state_dir)
    store.symlink_to(decoy)
    moved = state_dir / "orchestrator.sqlite.corrupt-source-symlink"
    intent = db._repair_intent_path(state_dir)
    intent.write_text(
        json.dumps({"version": 1, "target": moved.name, "files": ["main"]}),
        encoding="utf-8",
    )

    with pytest.raises(db.StoreUnavailableError):
        with db.locked_connect(state_dir):
            pass

    assert intent.is_file()
    assert store.is_symlink()
    assert not moved.exists()
    assert not os.path.lexists(moved)


def test_repair_intent_with_unlisted_wal_never_strands_the_sidecar(
    tmp_path: Path,
) -> None:
    """An intent listing only `main` while a live `-wal` exists must not be
    honoured: the read path fails closed and repair moves every present sidecar,
    so committed-but-uncheckpointed rows are preserved rather than dropped."""
    state_dir = tmp_path / "unlisted-wal"
    persist.run_tick(state_dir, tick_id="seed", noop=True)
    store = db.db_path(state_dir)
    keeper = sqlite3.connect(str(store), isolation_level=None)
    keeper.execute("PRAGMA wal_autocheckpoint = 0")
    keeper.execute(
        "INSERT INTO ticks "
        "(seq, tick_id, started_at, duration_ms, outcome, noop, overlap) "
        "VALUES (?, 'wal-only-in-unlisted', ?, 0, 'completed', 0, 0)",
        (db.MAX_TRUSTED_SEQ + 1, datetime.now(timezone.utc).isoformat()),
    )
    wal = Path(f"{store}-wal")
    assert wal.is_file() and wal.stat().st_size > 0
    moved = state_dir / "orchestrator.sqlite.corrupt-unlisted-wal"
    intent = db._repair_intent_path(state_dir)
    intent.write_text(
        json.dumps({"version": 1, "target": moved.name, "files": ["main"]}),
        encoding="utf-8",
    )

    try:
        # The read path refuses to act on the inconsistent intent at all.
        with pytest.raises(db.StoreUnavailableError):
            with db.locked_connect(state_dir):
                pass

        assert intent.is_file()
        assert wal.is_file()

        # Explicit repair does not honour the subset intent either: it
        # quarantines it and moves the store with every sidecar present, so the
        # committed-but-uncheckpointed WAL rows are preserved, not stranded.
        result = persist.repair_store(state_dir, stamp="unlisted-wal")
    finally:
        keeper.close()

    assert result == moved
    assert not intent.exists()
    assert len(list(state_dir.glob(".orchestrator-repair-intent.json.orphan-*"))) == 1
    assert Path(f"{moved}-wal").is_file()
    assert not wal.exists()
    assert not store.exists()

    moved_conn = sqlite3.connect(str(moved))
    try:
        assert moved_conn.execute(
            "SELECT COUNT(*) FROM ticks WHERE tick_id = 'wal-only-in-unlisted'"
        ).fetchone()[0] == 1
    finally:
        moved_conn.close()


def test_move_store_aside_records_every_present_sidecar(
    tmp_path: Path, monkeypatch
) -> None:
    """The intent written by `move_store_aside` lists each sidecar on disk, so
    recovery never strands one."""
    state_dir = tmp_path / "intent-lists-sidecars"
    persist.run_tick(state_dir, tick_id="seed", noop=True)
    store = db.db_path(state_dir)
    keeper = sqlite3.connect(str(store), isolation_level=None)
    keeper.execute("PRAGMA wal_autocheckpoint = 0")
    keeper.execute(
        "INSERT INTO ticks "
        "(seq, tick_id, started_at, duration_ms, outcome, noop, overlap) "
        "VALUES (?, 'wal-listed', ?, 0, 'completed', 0, 0)",
        (db.MAX_TRUSTED_SEQ + 1, datetime.now(timezone.utc).isoformat()),
    )
    moved = state_dir / "orchestrator.sqlite.corrupt-sidecar-intent"
    files: list[str] = []
    real_replace = Path.replace

    def capture_intent(source: Path, target: Path) -> Path:
        # The intent is on disk only until recovery unlinks it.
        if not files and db._repair_intent_path(state_dir).is_file():
            files.extend(
                json.loads(
                    db._repair_intent_path(state_dir).read_text(encoding="utf-8")
                )["files"]
            )
        return real_replace(source, target)

    monkeypatch.setattr(Path, "replace", capture_intent)
    try:
        result = persist.repair_store(state_dir, stamp="sidecar-intent")
    finally:
        keeper.close()
    monkeypatch.setattr(Path, "replace", real_replace)

    assert files == ["main", "wal", "shm"]
    assert result == moved
    assert Path(f"{moved}-wal").is_file()
    assert Path(f"{moved}-shm").is_file()


def test_repair_intent_with_nul_byte_target_is_corrupt_not_unavailable(
    tmp_path: Path,
) -> None:
    """A NUL byte cannot name a file. It reaches the rename as a ValueError,
    escaping every `StoreError` handler; classify it as corrupt intent."""
    state_dir = tmp_path / "nul-target"
    persist.run_tick(state_dir, tick_id="seed", noop=True)
    store = db.db_path(state_dir)
    Path(f"{store}-wal").unlink(missing_ok=True)
    Path(f"{store}-shm").unlink(missing_ok=True)
    conn = sqlite3.connect(str(store))
    try:
        conn.execute("DROP TABLE ticks")
        conn.commit()
    finally:
        conn.close()
    intent = db._repair_intent_path(state_dir)
    intent.write_text(
        json.dumps(
            {
                "version": 1,
                "target": "orchestrator.sqlite.corrupt-nul\x00x",
                "files": ["main"],
            }
        ),
        encoding="utf-8",
    )

    moved = persist.repair_store(state_dir, stamp="nul-target")

    assert moved == state_dir / "orchestrator.sqlite.corrupt-nul-target"
    assert moved.is_file()
    assert not store.exists()
    assert not intent.exists()
    assert len(list(state_dir.glob(".orchestrator-repair-intent.json.orphan-*"))) == 1


def test_start_tick_reraises_integrity_error_that_is_not_a_duplicate_tick_id(
    tmp_path: Path,
) -> None:
    """Only a tick_id collision is `DuplicateTickIdError`. A CHECK failure must
    surface as IntegrityError, not be mislabelled as a duplicate."""
    persist.run_tick(tmp_path, tick_id="seed", noop=True)
    conn = db.connect(tmp_path)
    try:
        # Violates the canonical CHECK tying duration_ms to a running outcome.
        conn.execute("PRAGMA ignore_check_constraints = OFF")
        with pytest.raises(sqlite3.IntegrityError) as excinfo:
            db.start_tick(
                conn,
                "fresh",
                "short",  # violates length(started_at) BETWEEN 20 AND 40
                cutoff_iso="2000-01-01T00:00:00+00:00",
            )
        assert not isinstance(excinfo.value, db.DuplicateTickIdError)
    finally:
        conn.close()


def test_start_tick_still_reports_duplicate_tick_id(tmp_path: Path) -> None:
    persist.run_tick(tmp_path, tick_id="taken", noop=True)
    conn = db.connect(tmp_path)
    try:
        with pytest.raises(db.DuplicateTickIdError):
            db.start_tick(
                conn,
                "taken",
                datetime.now(timezone.utc).isoformat(),
                cutoff_iso="2000-01-01T00:00:00+00:00",
            )
    finally:
        conn.close()


def test_repair_waits_for_a_tick_that_outlives_the_deadman_lock_timeout(
    tmp_path: Path, monkeypatch
) -> None:
    """Repair and writers wait for the tick lifecycle; only the dead-man read is
    bounded, so a longer-than-2s tick is not a spurious repair failure."""
    monkeypatch.setattr(db, "STORE_LOCK_TIMEOUT_SECONDS", 0.2, raising=False)
    state_dir = tmp_path / "long-tick"
    persist.run_tick(state_dir, tick_id="seed", noop=True)
    tick_started = threading.Event()
    release = threading.Event()

    def work() -> None:
        tick_started.set()
        assert release.wait(timeout=5)

    errors: list[BaseException] = []

    def run() -> None:
        try:
            persist.run_tick(state_dir, tick_id="slow", work=work)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    assert tick_started.wait(timeout=3)
    time.sleep(0.4)  # well past the 0.2s shared-lock timeout
    result: dict[str, Path] = {}
    repair_errors: list[BaseException] = []

    def repair() -> None:
        try:
            result["path"] = persist.repair_store(state_dir, stamp="slow")
        except BaseException as exc:
            repair_errors.append(exc)

    repair_thread = threading.Thread(target=repair)
    repair_thread.start()
    # Let the repair actually contend: with a 0.2s timeout it must still be
    # waiting long after that budget, because repair uses the lifecycle timeout.
    time.sleep(0.5)
    contended_while_held = repair_thread.is_alive()
    release.set()
    thread.join(timeout=5)
    repair_thread.join(timeout=5)

    assert not errors
    assert not repair_errors, repair_errors
    assert contended_while_held
    assert result["path"] == db.db_path(state_dir)


def test_deadman_read_stays_bounded_under_a_wedged_writer(
    tmp_path: Path, monkeypatch
) -> None:
    """The dead-man must never inherit the longer repair timeout."""
    monkeypatch.setattr(db, "STORE_LOCK_TIMEOUT_SECONDS", 3.0, raising=False)
    monkeypatch.setattr(db, "DEADMAN_LOCK_TIMEOUT_SECONDS", 0.1, raising=False)
    state_dir = tmp_path / "wedged"
    state_dir.mkdir()
    holder = os.open(state_dir, os.O_RDONLY)
    db.fcntl.flock(holder, db.fcntl.LOCK_EX)
    try:
        started = time.monotonic()
        verdict = deadman.evaluate_deadman(state_dir)
        elapsed = time.monotonic() - started
    finally:
        db.fcntl.flock(holder, db.fcntl.LOCK_UN)
        os.close(holder)

    assert verdict.ok is False
    assert verdict.reason == "heartbeat_unreadable"
    assert elapsed < 2.0


def test_repair_cli_reports_quarantined_intent_honestly(
    tmp_path: Path, capsys
) -> None:
    """An ambiguous intent is quarantined and the store is then repaired; the CLI
    must not claim there was nothing to move."""
    state_dir = tmp_path / "cli-quarantine"
    state_dir.mkdir()
    store = db.db_path(state_dir)
    conn = sqlite3.connect(str(store))
    try:
        conn.execute(
            "CREATE TABLE ticks ("
            "seq INTEGER PRIMARY KEY DESC DEFAULT 1, "
            "tick_id TEXT NOT NULL UNIQUE, "
            "started_at TEXT NOT NULL, "
            "duration_ms INTEGER, "
            "outcome TEXT NOT NULL DEFAULT 'running', "
            "noop INTEGER NOT NULL DEFAULT 0, "
            "overlap INTEGER NOT NULL DEFAULT 0, "
            "last_alert_ok INTEGER)"
        )
        conn.commit()
    finally:
        conn.close()
    old_target = state_dir / "orchestrator.sqlite.corrupt-old"
    shutil.copy2(store, old_target)
    db._repair_intent_path(state_dir).write_text(
        json.dumps({"version": 1, "target": old_target.name, "files": ["main"]}),
        encoding="utf-8",
    )

    assert persist.main(["repair", "--state-dir", str(state_dir)]) == 0

    out = capsys.readouterr().out.strip()
    assert out != "repair: no store to move"
    assert out.startswith("repair: moved corrupt store to ")
    assert len(list(state_dir.glob(".orchestrator-repair-intent.json.orphan-*"))) == 1


def test_repair_cli_reports_no_store_only_when_none_exists(
    tmp_path: Path, capsys
) -> None:
    state_dir = tmp_path / "cli-empty"
    state_dir.mkdir()

    assert persist.main(["repair", "--state-dir", str(state_dir)]) == 0

    assert capsys.readouterr().out.strip() == "repair: no store to move"


def test_repair_rejects_sampled_duration_check(
    tmp_path: Path,
) -> None:
    store = db.db_path(tmp_path)
    ddl = db._TABLE_SQL.replace(
        "duration_ms   INTEGER          CHECK "
        "(duration_ms IS NULL OR duration_ms >= 0)",
        "duration_ms   INTEGER          CHECK "
        "(duration_ms IS NULL OR duration_ms IN (0, 1, 2, 10, 1000))",
    )
    assert ddl != db._TABLE_SQL
    conn = sqlite3.connect(str(store))
    try:
        conn.executescript(ddl)
        conn.execute(
            "INSERT INTO ticks (tick_id, started_at, outcome) "
            "VALUES ('duration-check', ?, 'running')",
            (datetime.now(timezone.utc).isoformat(),),
        )
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE ticks SET outcome = 'completed', duration_ms = 55 "
                "WHERE tick_id = 'duration-check'"
            )
    finally:
        conn.close()

    moved = persist.repair_store(tmp_path, stamp="sampled-duration")

    assert moved == tmp_path / "orchestrator.sqlite.corrupt-sampled-duration"
    moved_conn = sqlite3.connect(str(moved))
    try:
        row = moved_conn.execute(
            "SELECT tick_id, outcome, duration_ms FROM ticks"
        ).fetchone()
    finally:
        moved_conn.close()
    assert row == ("duration-check", "running", None)


@pytest.mark.parametrize(
    "trigger_body",
    [
        "UPDATE sqlite_sequence SET seq=4611686018427387904 WHERE name='ticks'",
        'UPDATE "sqlite_sequence" SET seq=4611686018427387904 WHERE name="ticks"',
        "DELETE FROM [TiCkS]",
        "DELETE FROM 'ticks'",
        "SELECT * FROM [LaTeSt]",
        "SELECT unknown_trigger_function()",
    ],
)
def test_repair_rejects_off_target_trigger_that_can_damage_ticks(
    tmp_path: Path, trigger_body: str
) -> None:
    state_dir = tmp_path / "off-target-trigger"
    persist.run_tick(state_dir, tick_id="seed", noop=True)
    store = db.db_path(state_dir)
    conn = sqlite3.connect(str(store))
    try:
        conn.execute("CREATE TABLE auxiliary (value INTEGER)")
        conn.execute(
            "CREATE TRIGGER damage AFTER INSERT ON auxiliary "
            f"BEGIN {trigger_body}; END"
        )
        conn.commit()
    finally:
        conn.close()

    moved = persist.repair_store(state_dir, stamp="off-target-trigger")

    assert moved == state_dir / "orchestrator.sqlite.corrupt-off-target-trigger"
    assert moved.is_file()
    assert not store.exists()
    archived = sqlite3.connect(str(moved))
    try:
        assert archived.execute(
            "SELECT tick_id FROM ticks ORDER BY seq"
        ).fetchall() == [("seed",)]
    finally:
        archived.close()


@pytest.mark.parametrize(
    ("constraint", "action"),
    [
        ("unique", "REPLACE"),
        ("unique", "IGNORE"),
        ("unique", "FAIL"),
        ("unique", "ROLLBACK"),
        ("primary-key", "REPLACE"),
        ("primary-key", "IGNORE"),
        ("primary-key", "FAIL"),
        ("primary-key", "ROLLBACK"),
    ],
)
def test_repair_rejects_nondefault_constraint_conflict_action(
    tmp_path: Path, constraint: str, action: str
) -> None:
    store = db.db_path(tmp_path)
    ddl = db._TABLE_SQL
    if constraint == "unique":
        ddl = ddl.replace(
            "tick_id       TEXT    NOT NULL UNIQUE,",
            f"tick_id       TEXT    NOT NULL UNIQUE ON CONFLICT {action},",
        )
    else:
        ddl = ddl.replace(
            "seq           INTEGER PRIMARY KEY AUTOINCREMENT,",
            f"seq           INTEGER PRIMARY KEY ON CONFLICT {action} AUTOINCREMENT,",
        )
    assert ddl != db._TABLE_SQL
    conn = sqlite3.connect(str(store))
    try:
        conn.executescript(ddl)
        conn.execute(
            "INSERT INTO ticks (tick_id, started_at, duration_ms, outcome) "
            "VALUES ('seed', ?, 0, 'completed')",
            (datetime.now(timezone.utc).isoformat(),),
        )
        conn.commit()
    finally:
        conn.close()

    moved = persist.repair_store(
        tmp_path, stamp=f"conflict-{constraint}-{action.lower()}"
    )

    assert moved == tmp_path / (
        f"orchestrator.sqlite.corrupt-conflict-{constraint}-{action.lower()}"
    )
    archived = sqlite3.connect(str(moved))
    try:
        assert archived.execute(
            "SELECT tick_id, seq FROM ticks"
        ).fetchall() == [("seed", 1)]
    finally:
        archived.close()


def test_repair_rejects_duplicate_id_replace_conflict_policy(
    tmp_path: Path,
) -> None:
    store = db.db_path(tmp_path)
    ddl = db._TABLE_SQL.replace(
        "tick_id       TEXT    NOT NULL UNIQUE,",
        "tick_id       TEXT    NOT NULL UNIQUE ON CONFLICT REPLACE,",
    )
    assert ddl != db._TABLE_SQL
    conn = sqlite3.connect(str(store))
    try:
        conn.executescript(ddl)
        conn.execute(
            "INSERT INTO ticks (tick_id, started_at, duration_ms, outcome) "
            "VALUES ('same-id', ?, 0, 'completed')",
            (datetime.now(timezone.utc).isoformat(),),
        )
        conn.commit()
    finally:
        conn.close()

    moved = persist.repair_store(tmp_path, stamp="replace-conflict")

    assert moved == tmp_path / "orchestrator.sqlite.corrupt-replace-conflict"
    archived = sqlite3.connect(str(moved))
    try:
        assert archived.execute(
            "SELECT tick_id, seq FROM ticks"
        ).fetchall() == [("same-id", 1)]
    finally:
        archived.close()


def test_repair_keeps_explicit_default_abort_conflict_policy(
    tmp_path: Path,
) -> None:
    store = db.db_path(tmp_path)
    ddl = db._TABLE_SQL.replace(
        "tick_id       TEXT    NOT NULL UNIQUE,",
        "tick_id       TEXT    NOT NULL UNIQUE ON CONFLICT ABORT,",
    )
    assert ddl != db._TABLE_SQL
    conn = sqlite3.connect(str(store))
    try:
        conn.executescript(ddl)
        conn.execute(
            "INSERT INTO ticks (tick_id, started_at, duration_ms, outcome) "
            "VALUES ('seed', ?, 0, 'completed')",
            (datetime.now(timezone.utc).isoformat(),),
        )
        conn.commit()
    finally:
        conn.close()

    assert persist.repair_store(tmp_path, stamp="default-abort") == store
    with pytest.raises(db.DuplicateTickIdError):
        persist.run_tick(tmp_path, tick_id="seed", noop=True)


@pytest.mark.parametrize(
    "shape",
    [
        "started-at-nocase",
        "extra-nocase-index",
        "generated-column",
        "strict",
        "foreign-key",
        "duplicate-check",
    ],
)
def test_repair_rejects_unsupported_ticks_schema_modifiers(
    tmp_path: Path, shape: str
) -> None:
    store = db.db_path(tmp_path)
    ddl = db._TABLE_SQL
    if shape == "started-at-nocase":
        ddl = ddl.replace(
            "started_at    TEXT    NOT NULL CHECK",
            "started_at    TEXT    COLLATE NOCASE NOT NULL CHECK",
        )
    elif shape == "generated-column":
        ddl = ddl.replace(
            "last_alert_ok INTEGER          CHECK",
            "display TEXT GENERATED ALWAYS AS (tick_id) VIRTUAL,\n"
            "    last_alert_ok INTEGER          CHECK",
        )
    elif shape == "strict":
        ddl = ddl.rstrip() + " STRICT"
    conn = sqlite3.connect(str(store))
    try:
        if shape == "foreign-key":
            conn.execute("CREATE TABLE auxiliary (value TEXT PRIMARY KEY)")
            ddl = ddl.replace(
                "last_alert_ok INTEGER          CHECK",
                "last_alert_ok INTEGER          CHECK",
            ).rstrip()
            ddl = ddl[:-1] + (
                ", FOREIGN KEY (last_alert_ok) REFERENCES auxiliary(value))"
            )
        elif shape == "duplicate-check":
            ddl = ddl.replace(
                "last_alert_ok INTEGER          CHECK "
                "(last_alert_ok IS NULL OR last_alert_ok IN (0, 1)),",
                "last_alert_ok INTEGER          CHECK "
                "(last_alert_ok IS NULL OR last_alert_ok IN (0, 1)), "
                "CHECK (noop IN (0, 1)),",
            )
        conn.executescript(ddl)
        if shape == "extra-nocase-index":
            conn.execute(
                "CREATE INDEX started_at_nocase ON ticks(started_at COLLATE NOCASE)"
            )
        conn.execute(
            "INSERT INTO ticks (tick_id, started_at, duration_ms, outcome) "
            "VALUES ('seed', ?, 0, 'completed')",
            (datetime.now(timezone.utc).isoformat(),),
        )
        conn.commit()
    finally:
        conn.close()

    moved = persist.repair_store(tmp_path, stamp=shape)

    assert moved == tmp_path / f"orchestrator.sqlite.corrupt-{shape}"
    assert moved.is_file()


def test_repair_rejects_noncanonical_latest_view(tmp_path: Path) -> None:
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(str(store))
    try:
        conn.executescript(db._TABLE_SQL)
        conn.execute(
            "INSERT INTO ticks (tick_id, started_at, duration_ms, outcome) "
            "VALUES ('seed', ?, 0, 'completed')",
            (datetime.now(timezone.utc).isoformat(),),
        )
        conn.execute("CREATE VIEW latest AS SELECT tick_id FROM ticks")
        conn.commit()
    finally:
        conn.close()

    moved = persist.repair_store(tmp_path, stamp="noncanonical-latest-view")

    assert moved == tmp_path / "orchestrator.sqlite.corrupt-noncanonical-latest-view"
    assert moved.is_file()


def test_repair_keeps_unrelated_autoincrement_table_and_analyze_metadata(
    tmp_path: Path,
) -> None:
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(str(store))
    try:
        conn.executescript(db._TABLE_SQL)
        conn.execute(
            "CREATE TABLE auxiliary (seq INTEGER PRIMARY KEY AUTOINCREMENT, value TEXT)"
        )
        conn.execute("INSERT INTO auxiliary(value) VALUES ('independent')")
        conn.execute(
            "INSERT INTO ticks (tick_id, started_at, duration_ms, outcome) "
            "VALUES ('seed', ?, 0, 'completed')",
            (datetime.now(timezone.utc).isoformat(),),
        )
        conn.execute("ANALYZE")
        conn.commit()
    finally:
        conn.close()

    assert persist.repair_store(tmp_path, stamp="analyzed-auxiliary") == store
    assert persist.read_latest_tick(tmp_path)["tick_id"] == "seed"


@pytest.mark.parametrize(
    "shape",
    ["duplicate", "noninteger", "behind-row", "missing"],
)
def test_repair_rejects_inconsistent_ticks_sequence_metadata(
    tmp_path: Path, shape: str
) -> None:
    persist.run_tick(tmp_path, tick_id="seed", noop=True)
    conn = db.connect(tmp_path)
    try:
        if shape == "duplicate":
            conn.execute(
                "INSERT INTO sqlite_sequence(name, seq) VALUES ('ticks', 1)"
            )
        elif shape == "noninteger":
            conn.execute(
                "UPDATE sqlite_sequence SET seq='not-an-integer' WHERE name='ticks'"
            )
        elif shape == "behind-row":
            conn.execute(
                "UPDATE sqlite_sequence SET seq=0 WHERE name='ticks'"
            )
        else:
            conn.execute("DELETE FROM sqlite_sequence WHERE name='ticks'")
    finally:
        conn.close()

    moved = persist.repair_store(tmp_path, stamp=f"sequence-{shape}")

    assert moved == tmp_path / f"orchestrator.sqlite.corrupt-sequence-{shape}"
    assert moved.is_file()


def test_repair_rejects_internal_rowid_shadow_column(
    tmp_path: Path,
) -> None:
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(str(store))
    try:
        conn.execute(
            "CREATE TABLE ticks ("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, "
            "_rowid_ TEXT, "
            "tick_id TEXT NOT NULL UNIQUE, "
            "started_at TEXT NOT NULL, "
            "duration_ms INTEGER, "
            "outcome TEXT NOT NULL DEFAULT 'running', "
            "noop INTEGER NOT NULL DEFAULT 0, "
            "overlap INTEGER NOT NULL DEFAULT 0, "
            "last_alert_ok INTEGER)"
        )
        conn.execute(
            "INSERT INTO ticks (tick_id, started_at, duration_ms, outcome) "
            "VALUES ('seed', ?, 0, 'completed')",
            (datetime.now(timezone.utc).isoformat(),),
        )
        conn.commit()
    finally:
        conn.close()

    moved = persist.repair_store(tmp_path, stamp="internal-rowid-shadow")

    assert moved == tmp_path / "orchestrator.sqlite.corrupt-internal-rowid-shadow"
    assert moved.is_file()
    assert not store.exists()


def test_repair_keeps_canonical_store_without_latest_view(
    tmp_path: Path,
) -> None:
    store = db.db_path(tmp_path)
    conn = sqlite3.connect(str(store))
    try:
        conn.executescript(db._TABLE_SQL)
        conn.execute(
            "INSERT INTO ticks (tick_id, started_at, duration_ms, outcome) "
            "VALUES ('seed', ?, 0, 'completed')",
            (datetime.now(timezone.utc).isoformat(),),
        )
        conn.commit()
    finally:
        conn.close()

    assert persist.repair_store(tmp_path, stamp="missing-latest") == store
    assert persist.read_latest_tick(tmp_path)["tick_id"] == "seed"


def test_start_tick_refuses_exhausted_sequence_before_sweeping(
    tmp_path: Path,
) -> None:
    persist.run_tick(tmp_path, tick_id="seed", noop=True)
    conn = db.connect(tmp_path)
    stale_start = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    try:
        conn.execute(
            "INSERT INTO ticks (tick_id, started_at, outcome, overlap) "
            "VALUES ('stale-running', ?, 'running', 0)",
            (stale_start,),
        )
        conn.execute(
            "UPDATE sqlite_sequence SET seq=? WHERE name='ticks'",
            (db.MAX_TRUSTED_SEQ,),
        )
    finally:
        conn.close()

    with pytest.raises(db.StoreCorruptError):
        persist.run_tick(tmp_path, tick_id="must-not-start", noop=True)

    check = sqlite3.connect(str(db.db_path(tmp_path)))
    try:
        assert check.execute(
            "SELECT outcome FROM ticks WHERE tick_id='stale-running'"
        ).fetchone() == ("running",)
        assert check.execute(
            "SELECT seq FROM sqlite_sequence WHERE name='ticks'"
        ).fetchone() == (db.MAX_TRUSTED_SEQ,)
        assert check.execute(
            "SELECT 1 FROM ticks WHERE tick_id='must-not-start'"
        ).fetchone() is None
    finally:
        check.close()


def test_start_tick_reserves_the_last_trusted_sequence(
    tmp_path: Path,
) -> None:
    persist.run_tick(tmp_path, tick_id="seed", noop=True)
    conn = db.connect(tmp_path)
    try:
        conn.execute(
            "UPDATE sqlite_sequence SET seq=? WHERE name='ticks'",
            (db.MAX_TRUSTED_SEQ - 1,),
        )
    finally:
        conn.close()

    final = persist.run_tick(tmp_path, tick_id="last-trusted", noop=True)
    assert final.seq == db.MAX_TRUSTED_SEQ

    with pytest.raises(db.StoreCorruptError):
        persist.run_tick(tmp_path, tick_id="over-trusted", noop=True)

    check = sqlite3.connect(str(db.db_path(tmp_path)))
    try:
        assert check.execute(
            "SELECT seq, tick_id FROM ticks ORDER BY seq DESC LIMIT 1"
        ).fetchone() == (db.MAX_TRUSTED_SEQ, "last-trusted")
    finally:
        check.close()


def test_repair_quarantines_store_without_sequence_headroom(
    tmp_path: Path,
) -> None:
    persist.run_tick(tmp_path, tick_id="seed", noop=True)
    conn = db.connect(tmp_path)
    try:
        conn.execute(
            "UPDATE sqlite_sequence SET seq=? WHERE name='ticks'",
            (db.MAX_TRUSTED_SEQ,),
        )
    finally:
        conn.close()

    moved = persist.repair_store(tmp_path, stamp="no-sequence-headroom")

    assert moved == tmp_path / "orchestrator.sqlite.corrupt-no-sequence-headroom"
    assert moved.is_file()
    assert not db.db_path(tmp_path).exists()


def _create_lost_wal_repair_state(state_dir: Path) -> tuple[Path, bytes]:
    persist.run_tick(state_dir, tick_id="seed", noop=True)
    store = db.db_path(state_dir)
    script = (
        "import os, sqlite3, sys; "
        "p=sys.argv[1]; c=sqlite3.connect(p, isolation_level=None); "
        "c.execute('PRAGMA journal_mode=WAL'); "
        "c.execute('PRAGMA synchronous=NORMAL'); "
        "c.execute('PRAGMA wal_autocheckpoint=0'); "
        "c.execute(\"INSERT INTO ticks "
        "(seq,tick_id,started_at,duration_ms,outcome,noop,overlap) "
        "VALUES (2,'wal-only', '2026-01-01T00:00:00+00:00',0,'completed',0,0)\"); "
        "os._exit(0)"
    )
    subprocess.run(
        [sys.executable, "-c", script, str(store)],
        cwd=_REPO_ROOT,
        check=True,
    )
    wal = Path(f"{store}-wal")
    assert wal.is_file()
    wal_backup = wal.read_bytes()
    immutable = sqlite3.connect(f"{store.as_uri()}?immutable=1", uri=True)
    try:
        assert immutable.execute(
            "SELECT COUNT(*) FROM ticks WHERE tick_id='wal-only'"
        ).fetchone() == (0,)
    finally:
        immutable.close()

    target = state_dir / "orchestrator.sqlite.corrupt-lost-wal"
    db._repair_intent_path(state_dir).write_text(
        json.dumps(
            {"version": 1, "target": target.name, "files": ["main", "wal"]}
        ),
        encoding="utf-8",
    )
    store.replace(target)
    wal.unlink()
    Path(f"{store}-shm").unlink(missing_ok=True)
    return target, wal_backup


def _run_repair_cli(state_dir: Path, *options: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from tools.review_orchestrator.persist import main; "
            "raise SystemExit(main())",
            "repair",
            "--state-dir",
            str(state_dir),
            *options,
        ],
        cwd=_REPO_ROOT,
        text=True,
        capture_output=True,
    )


def test_missing_wal_blocks_cli_and_keeps_intent_without_creating_store(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "lost-wal"
    state_dir.mkdir()
    target, _ = _create_lost_wal_repair_state(state_dir)
    before = target.read_bytes()

    result = _run_repair_cli(state_dir)

    assert result.returncode == 2
    assert (
        "repair: blocked: expected WAL missing at source and target; "
        "intent retained; target=orchestrator.sqlite.corrupt-lost-wal"
    ) in result.stderr
    assert db._repair_intent_path(state_dir).is_file()
    assert target.read_bytes() == before
    assert not db.db_path(state_dir).exists()
    assert not Path(f"{db.db_path(state_dir)}-wal").exists()
    with pytest.raises(db.StoreUnavailableError):
        persist.read_latest_tick(state_dir)
    assert not db.db_path(state_dir).exists()


def test_acknowledging_lost_wal_quarantines_intent_and_preserves_archive(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "acknowledged-lost-wal"
    state_dir.mkdir()
    target, _ = _create_lost_wal_repair_state(state_dir)
    before = target.read_bytes()

    result = _run_repair_cli(state_dir, "--acknowledge-wal-loss")

    assert result.returncode == 0
    assert "WAL data is unrecoverable" in result.stdout
    assert "archived main preserved" in result.stdout
    assert "next start will create a fresh store" in result.stdout
    assert not db._repair_intent_path(state_dir).exists()
    assert len(
        list(state_dir.glob(".orchestrator-repair-intent.json.orphan-*"))
    ) == 1
    assert target.read_bytes() == before
    assert not db.db_path(state_dir).exists()


def test_wal_loss_acknowledgement_is_rejected_without_matching_intent(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "not-a-wal-loss"
    persist.run_tick(state_dir, tick_id="healthy", noop=True)
    before = db.db_path(state_dir).read_bytes()

    result = _run_repair_cli(state_dir, "--acknowledge-wal-loss")

    assert result.returncode == 2
    assert "no pending repair intent to acknowledge" in result.stderr
    assert db.db_path(state_dir).read_bytes() == before
    assert not db._repair_intent_path(state_dir).exists()


def test_restoring_consistent_backup_wal_resumes_pending_repair(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "restored-wal"
    state_dir.mkdir()
    target, wal_backup = _create_lost_wal_repair_state(state_dir)
    with pytest.raises(db.StoreUnavailableError):
        with db.locked_connect(state_dir):
            pass
    Path(f"{target}-wal").write_bytes(wal_backup)

    assert persist.repair_store(state_dir, stamp="restored-wal") == target
    assert not db._repair_intent_path(state_dir).exists()

    conn = sqlite3.connect(str(target))
    try:
        assert conn.execute(
            "SELECT tick_id FROM ticks WHERE tick_id='wal-only'"
        ).fetchone() == ("wal-only",)
    finally:
        conn.close()
