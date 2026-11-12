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


def test_repair_rejects_composite_seq_primary_key_with_matching_probe_values(
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
        "started_at TEXT NOT NULL, "
        "duration_ms INTEGER, "
        "outcome TEXT NOT NULL DEFAULT 'running', "
        "noop INTEGER NOT NULL DEFAULT 0, "
        "overlap INTEGER NOT NULL DEFAULT 0, "
        "last_alert_ok INTEGER)"
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


def test_repair_completes_intent_when_wal_and_shm_are_absent(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "missing-sidecars"
    persist.run_tick(state_dir, tick_id="seed", noop=True)
    store = db.db_path(state_dir)
    for suffix in ("-wal", "-shm"):
        Path(f"{store}{suffix}").unlink(missing_ok=True)
    moved = state_dir / "orchestrator.sqlite.corrupt-stale"
    db._repair_intent_path(state_dir).write_text(
        json.dumps({"version": 1, "target": moved.name, "files": ["main", "wal", "shm"]}),
        encoding="utf-8",
    )

    result = persist.repair_store(state_dir, stamp="stale-intent")

    assert result == store
    assert moved.is_file()
    assert not store.exists()
    assert not db._repair_intent_path(state_dir).exists()


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

    monkeypatch.setattr(deadman.db, "connect", boom)
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
