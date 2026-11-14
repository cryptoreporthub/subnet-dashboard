"""Store contract tests (behavior, not implementation)."""

from __future__ import annotations

import contextlib
import errno
import multiprocessing as mp
import os
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import tools.review_orchestrator.deadman as deadman
import tools.review_orchestrator.exam_v0 as exam_v0
import tools.review_orchestrator.persist as persist
from tools.review_orchestrator import db
from tools.review_orchestrator.db import (
    DuplicateTickIdError,
    StoreCorruptError,
    StoreUnavailableError,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


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


def _plant_running(state_dir: Path, tick_id: str, started_at: str) -> None:
    conn = db.connect(state_dir)
    try:
        conn.execute(
            "INSERT INTO ticks (tick_id, started_at, overlap) VALUES (?, ?, 0)",
            (tick_id, started_at),
        )
    finally:
        conn.close()


def test_run_tick_completes_row(tmp_path: Path) -> None:
    result = persist.run_tick(tmp_path, tick_id="alpha", noop=False)
    assert result.seq == 1
    assert result.outcome == "completed"
    assert result.overlap is False
    rows = _rows(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["tick_id"] == "alpha"
    assert row["outcome"] == "completed"
    assert row["noop"] == 0
    assert isinstance(row["duration_ms"], int)
    assert row["duration_ms"] >= 0
    assert persist.parse_utc_iso(row["started_at"]) is not None


def test_run_tick_rejects_duplicate_tick_id(tmp_path: Path) -> None:
    persist.run_tick(tmp_path, tick_id="dup", noop=True)
    with pytest.raises(DuplicateTickIdError):
        persist.run_tick(tmp_path, tick_id="dup", noop=True)
    assert len([r for r in _rows(tmp_path) if r["tick_id"] == "dup"]) == 1


def test_concurrent_duplicate_tick_id_never_double_winner(tmp_path: Path) -> None:
    for round_idx in range(300):
        round_dir = tmp_path / f"round-{round_idx}"
        round_dir.mkdir()
        barrier = threading.Barrier(2)
        successes: list = []
        rejected: list = []
        lock = threading.Lock()

        def worker() -> None:
            barrier.wait(timeout=3)
            try:
                result = persist.run_tick(round_dir, tick_id="dup-id", noop=True)
                with lock:
                    successes.append(result)
            except DuplicateTickIdError:
                with lock:
                    rejected.append(1)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert len(successes) == 1, f"round {round_idx}"
        assert len(rejected) == 1, f"round {round_idx}"


def test_seq_unique_under_parallel_threads(tmp_path: Path) -> None:
    barrier = threading.Barrier(8)
    seqs: list[int] = []
    lock = threading.Lock()

    def worker(idx: int) -> None:
        barrier.wait(timeout=3)
        result = persist.run_tick(tmp_path, tick_id=f"par-{idx}", noop=True)
        with lock:
            seqs.append(result.seq)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert len(seqs) == 8
    assert len(set(seqs)) == 8


def _barrier_seq_worker(store: str, barrier, out) -> None:
    from tools.review_orchestrator.persist import run_tick

    barrier.wait(timeout=5)
    result = run_tick(Path(store), tick_id=secrets.token_hex(4), noop=True)
    out.put(result.seq)


def test_seq_unique_under_barrier_processes(tmp_path: Path) -> None:
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(4)
    out = ctx.Queue()
    store = str(tmp_path)
    procs = [
        ctx.Process(target=_barrier_seq_worker, args=(store, barrier, out))
        for _ in range(4)
    ]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(timeout=25)
    seqs = [out.get_nowait() for _ in range(4)]
    assert len(set(seqs)) == 4


def test_overlap_reported_against_running_row(tmp_path: Path) -> None:
    _plant_running(tmp_path, "holder", datetime.now(timezone.utc).isoformat())
    result = persist.run_tick(tmp_path, tick_id="challenger", noop=True)
    assert result.overlap is True
    rows = _rows(tmp_path)
    assert rows[-1]["overlap"] == 1


def test_sequential_ticks_do_not_report_overlap(tmp_path: Path) -> None:
    first = persist.run_tick(tmp_path, tick_id="one", noop=False)
    second = persist.run_tick(tmp_path, tick_id="two", noop=False)
    assert first.overlap is False
    assert second.overlap is False


def test_crash_mid_tick_row_swept_so_overlap_recovers(tmp_path: Path) -> None:
    old = datetime.now(timezone.utc) - timedelta(minutes=41)
    _plant_running(tmp_path, "killed", old.isoformat())
    result = persist.run_tick(tmp_path, tick_id="next", noop=True)
    assert result.overlap is False
    outcomes = {row["tick_id"]: row["outcome"] for row in _rows(tmp_path)}
    assert outcomes["killed"] == "abandoned"


def test_raised_work_writes_failed_outcome_with_duration(tmp_path: Path) -> None:
    def boom() -> None:
        raise RuntimeError("simulated work failure")

    with pytest.raises(RuntimeError, match="simulated work failure"):
        persist.run_tick(tmp_path, tick_id="fail", noop=False, work=boom)
    row = _rows(tmp_path)[0]
    assert row["outcome"] == "failed"
    assert row["duration_ms"] is not None
    assert persist.read_latest_tick(tmp_path)["outcome"] == "failed"


def test_schema_rejects_completed_without_duration(tmp_path: Path) -> None:
    conn = db.connect(tmp_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO ticks (tick_id, started_at, outcome, duration_ms) "
                "VALUES ('x', ?, 'completed', NULL)",
                (datetime.now(timezone.utc).isoformat(),),
            )
    finally:
        conn.close()


def test_schema_rejects_running_with_duration(tmp_path: Path) -> None:
    conn = db.connect(tmp_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO ticks (tick_id, started_at, outcome, duration_ms) "
                "VALUES ('y', ?, 'running', 5)",
                (datetime.now(timezone.utc).isoformat(),),
            )
    finally:
        conn.close()


def test_corrupt_store_raises_storecorrupt(tmp_path: Path) -> None:
    db.db_path(tmp_path).write_text("not a database", encoding="utf-8")
    with pytest.raises(StoreCorruptError):
        persist.run_tick(tmp_path, tick_id="x", noop=True)


def test_repair_moves_corrupt_store_aside(tmp_path: Path) -> None:
    db.db_path(tmp_path).write_text("not a database", encoding="utf-8")
    moved = persist.repair_store(tmp_path)
    assert moved != db.db_path(tmp_path)
    assert moved.is_file()
    assert not db.db_path(tmp_path).exists()
    result = persist.run_tick(tmp_path, tick_id="recovered", noop=True)
    assert result.seq == 1


def test_seq_guard_rejects_untrusted_max_seq(tmp_path: Path) -> None:
    conn = db.connect(tmp_path)
    try:
        conn.execute(
            "INSERT INTO ticks (seq, tick_id, started_at, outcome, noop, overlap) "
            "VALUES (?, 'bogus', ?, 'abandoned', 0, 0)",
            (db.MAX_TRUSTED_SEQ + 1, datetime.now(timezone.utc).isoformat()),
        )
    finally:
        conn.close()
    with pytest.raises(StoreCorruptError):
        persist.run_tick(tmp_path, tick_id="next", noop=True)
    persist.repair_store(tmp_path)
    assert persist.run_tick(tmp_path, tick_id="repaired", noop=True).seq == 1


def test_deleted_store_recovers(tmp_path: Path) -> None:
    persist.run_tick(tmp_path, tick_id="first", noop=True)
    db.db_path(tmp_path).unlink()
    for suffix in ("-wal", "-shm"):
        side = Path(str(db.db_path(tmp_path)) + suffix)
        if side.exists():
            side.unlink()
    result = persist.run_tick(tmp_path, tick_id="second", noop=True)
    assert result.seq == 1
    assert persist.read_latest_tick(tmp_path)["tick_id"] == "second"


def test_store_init_is_idempotent(tmp_path: Path) -> None:
    persist.run_tick(tmp_path, tick_id="a", noop=True)
    for _ in range(3):
        conn = db.connect(tmp_path)
        conn.close()
    assert len(_rows(tmp_path)) == 1


def test_latest_row_is_max_seq(tmp_path: Path) -> None:
    persist.run_tick(tmp_path, tick_id="a", noop=True)
    persist.run_tick(tmp_path, tick_id="b", noop=True)
    persist.run_tick(tmp_path, tick_id="c", noop=True)
    rows = _rows(tmp_path)
    assert persist.read_latest_tick(tmp_path)["seq"] == max(r["seq"] for r in rows)


def test_seq_is_durable_across_subprocess(tmp_path: Path) -> None:
    persist.run_tick(tmp_path, tick_id="parent", noop=False)
    store = str(tmp_path)
    code = (
        "from pathlib import Path\n"
        "from tools.review_orchestrator.persist import run_tick\n"
        f"run_tick(Path({store!r}), tick_id='child', noop=False)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    subprocess.run([sys.executable, "-c", code], check=True, env=env, cwd=str(_REPO_ROOT))
    assert [row["seq"] for row in _rows(tmp_path)] == [1, 2]


def test_exam_state_dir_parent_is_rerunnable(tmp_path: Path) -> None:
    parent = tmp_path / "real-store"
    parent.mkdir()
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    cmd = [
        sys.executable,
        "-m",
        "tools.review_orchestrator.exam_v0",
        "--state-dir",
        str(parent),
    ]
    for _ in range(2):
        subprocess.run(cmd, check=True, env=env, cwd=str(_REPO_ROOT))
    assert list(parent.iterdir()) == []


def test_exam_passes_unmutated(tmp_path: Path) -> None:
    assert exam_v0.run_exam(tmp_path / "clean") == 0


def test_mutation_exam_detects_broken_seq_order(tmp_path: Path, monkeypatch) -> None:
    real = exam_v0._read_rows

    def reversed_seq(state_dir: Path) -> list[dict]:
        rows = real(state_dir)
        total = len(rows)
        return [{**row, "seq": total - row["seq"]} for row in rows]

    monkeypatch.setattr(exam_v0, "_read_rows", reversed_seq)
    assert exam_v0.run_exam(tmp_path / "mut_seq") == 1

    monkeypatch.setattr(exam_v0, "_read_rows", real)
    assert exam_v0.run_exam(tmp_path / "clean_seq") == 0


def test_mutation_exam_detects_remapped_tick_ids(tmp_path: Path, monkeypatch) -> None:
    real = exam_v0._read_rows

    def remapped(state_dir: Path) -> list[dict]:
        rows = real(state_dir)
        return [{**row, "tick_id": "wrong-" + row["tick_id"]} for row in rows]

    monkeypatch.setattr(exam_v0, "_read_rows", remapped)
    assert exam_v0.run_exam(tmp_path / "mut_ids") == 1

    monkeypatch.setattr(exam_v0, "_read_rows", real)
    assert exam_v0.run_exam(tmp_path / "clean_ids") == 0


# --- corruption vs unavailability ---------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "unable to open database file",
        "attempt to write a readonly database",
        "disk I/O error",
    ],
)
def test_unavailable_failures_are_not_reported_as_corruption(
    tmp_path: Path, monkeypatch, message: str
) -> None:
    def boom(*_args, **_kwargs):
        raise sqlite3.OperationalError(message)

    monkeypatch.setattr(db.sqlite3, "connect", boom)
    with pytest.raises(StoreUnavailableError):
        persist.run_tick(tmp_path, tick_id="x", noop=True)


def test_wal_conversion_preserves_permanent_operational_error() -> None:
    class Cursor:
        def fetchone(self):
            return ("delete",)

    class Connection:
        attempts = 0

        def execute(self, sql):
            if sql == "PRAGMA journal_mode":
                return Cursor()
            self.attempts += 1
            raise sqlite3.OperationalError("disk I/O error")

    conn = Connection()
    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        db._ensure_wal(conn, attempts=3)
    assert conn.attempts == 1


def test_connect_closes_connection_when_setup_fails(
    tmp_path: Path, monkeypatch
) -> None:
    real_connect = sqlite3.connect
    opened: list[sqlite3.Connection] = []

    def tracked_connect(*_args, **_kwargs):
        conn = real_connect(":memory:")
        opened.append(conn)
        return conn

    def fail_wal_setup(*_args, **_kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(db.sqlite3, "connect", tracked_connect)
    monkeypatch.setattr(db, "_ensure_wal", fail_wal_setup)

    with pytest.raises(StoreUnavailableError):
        db.connect(tmp_path)

    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        opened[0].execute("SELECT 1")


def test_locked_rollback_journal_wal_conversion_is_bounded(
    tmp_path: Path,
) -> None:
    store = db.db_path(tmp_path)
    raw = sqlite3.connect(str(store), isolation_level=None)
    try:
        raw.execute("CREATE TABLE lock_probe (value INTEGER)")
        raw.execute("BEGIN")
        raw.execute("SELECT * FROM lock_probe").fetchall()

        code = (
            "import sqlite3, sys, time\n"
            "from pathlib import Path\n"
            "from tools.review_orchestrator import db\n"
            "db.BUSY_TIMEOUT_MS = 1\n"
            "started = time.monotonic()\n"
            "try:\n"
            "    db.connect(Path(sys.argv[1]))\n"
            "except sqlite3.OperationalError as exc:\n"
            "    elapsed = time.monotonic() - started\n"
            "    print(type(exc).__name__ + ':' + str(exc) + ';elapsed=' + str(elapsed))\n"
            "else:\n"
            "    raise SystemExit(2)\n"
        )
        env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
        started = time.monotonic()
        try:
            result = subprocess.run(
                [sys.executable, "-c", code, str(tmp_path)],
                capture_output=True,
                text=True,
                env=env,
                cwd=str(_REPO_ROOT),
                timeout=3.0,
                check=False,
            )
        except subprocess.TimeoutExpired:
            pytest.fail("WAL conversion exceeded the bounded wait")
        elapsed = time.monotonic() - started
    finally:
        raw.rollback()
        raw.close()

    assert result.returncode == 0
    assert result.stdout.startswith("OperationalError:")
    assert "locked" in result.stdout.lower() or "busy" in result.stdout.lower()
    operation_elapsed = float(result.stdout.rsplit(";elapsed=", 1)[1].strip())
    assert operation_elapsed < 0.9
    assert elapsed < 3.0


def test_corrupt_markers_still_map_to_corruption(tmp_path: Path, monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise sqlite3.OperationalError("file is not a database")

    monkeypatch.setattr(db.sqlite3, "connect", boom)
    with pytest.raises(StoreCorruptError):
        persist.run_tick(tmp_path, tick_id="x", noop=True)


def test_unavailable_and_corrupt_are_distinct_types() -> None:
    assert not issubclass(StoreUnavailableError, StoreCorruptError)
    assert not issubclass(StoreCorruptError, StoreUnavailableError)
    # Siblings, but one base: a reader can name a single type in its except
    # clause and cannot miss a third store error added later.
    assert issubclass(StoreUnavailableError, db.StoreError)
    assert issubclass(StoreCorruptError, db.StoreError)


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


def test_repair_in_read_only_directory_raises_unavailable(tmp_path: Path) -> None:
    """A real read-only directory: repair cannot move the store, and says so."""
    _require_unprivileged()
    state = tmp_path / "store"
    state.mkdir()
    store = db.db_path(state)
    store.write_text("not a database", encoding="utf-8")

    with _read_only(state):
        with pytest.raises(StoreUnavailableError):
            persist.repair_store(state)
        # Nothing happened: the corrupt store is still sitting there, unnamed.
        assert list(state.iterdir()) == [store]


def test_repair_maps_a_read_only_filesystem_to_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    """EROFS needs a privileged read-only mount, so fail the rename the way the
    kernel would: an OSError from the move must not escape as a traceback."""
    db.db_path(tmp_path).write_text("not a database", encoding="utf-8")

    def read_only_filesystem(self, target):
        raise OSError(errno.EROFS, "Read-only file system")

    monkeypatch.setattr(Path, "replace", read_only_filesystem)
    with pytest.raises(StoreUnavailableError):
        persist.repair_store(tmp_path)


# --- atomicity of the tick transitions ----------------------------------


def test_complete_tick_replay_is_a_no_op(tmp_path: Path) -> None:
    result = persist.run_tick(tmp_path, tick_id="once", noop=False)
    before = {row["tick_id"]: row for row in _rows(tmp_path)}["once"]
    conn = db.connect(tmp_path)
    try:
        db.complete_tick(
            conn,
            result.seq,
            outcome=before["outcome"],
            duration_ms=before["duration_ms"],
            noop=bool(before["noop"]),
            last_alert_ok=None,
        )
    finally:
        conn.close()
    after = {row["tick_id"]: row for row in _rows(tmp_path)}["once"]
    assert after["outcome"] == "completed"
    assert after["duration_ms"] == before["duration_ms"]


def test_sweep_and_overlap_are_atomic_with_the_insert(tmp_path: Path) -> None:
    persist.run_tick(tmp_path, tick_id="taken", noop=True)
    old = datetime.now(timezone.utc) - timedelta(minutes=41)
    _plant_running(tmp_path, "killed", old.isoformat())

    with pytest.raises(DuplicateTickIdError):
        persist.run_tick(tmp_path, tick_id="taken", noop=True)

    outcomes = {row["tick_id"]: row["outcome"] for row in _rows(tmp_path)}
    assert outcomes["killed"] == "running"
    assert outcomes["taken"] == "completed"


def test_schema_rejects_non_boolean_last_alert_ok(tmp_path: Path) -> None:
    conn = db.connect(tmp_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO ticks "
                "(tick_id, started_at, outcome, duration_ms, last_alert_ok) "
                "VALUES ('z', ?, 'completed', 1, 2)",
                (datetime.now(timezone.utc).isoformat(),),
            )
    finally:
        conn.close()


# --- the newest row is chosen by seq, never by time ---------------------

_STALE_VIEW_SQL = (
    "CREATE VIEW latest AS SELECT seq, tick_id, started_at, duration_ms, outcome, "
    "noop, overlap, last_alert_ok FROM ticks ORDER BY started_at ASC LIMIT 1"
)


def test_latest_is_newest_seq_even_when_a_later_tick_starts_earlier(
    tmp_path: Path, monkeypatch
) -> None:
    base = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(persist, "utc_now", lambda: base)
    persist.run_tick(tmp_path, tick_id="first", noop=True)
    # Backward clock step: the next tick holds the newest seq but an earlier time.
    monkeypatch.setattr(persist, "utc_now", lambda: base - timedelta(hours=2))
    persist.run_tick(tmp_path, tick_id="second", noop=True)

    rows = _rows(tmp_path)
    assert [row["tick_id"] for row in rows] == ["first", "second"]
    assert rows[1]["seq"] > rows[0]["seq"]
    assert rows[1]["started_at"] < rows[0]["started_at"]
    assert persist.read_latest_tick(tmp_path)["tick_id"] == "second"
    backward_verdict = deadman.evaluate_deadman(
        tmp_path, max_age_minutes=40, now=base
    )
    assert backward_verdict.ok is False
    assert backward_verdict.reason == "completed_stale"

    monkeypatch.setattr(persist, "utc_now", lambda: base)
    persist.run_tick(tmp_path, tick_id="recovered", noop=True)
    recovered_verdict = deadman.evaluate_deadman(
        tmp_path, max_age_minutes=40, now=base
    )
    assert recovered_verdict.ok is False
    assert recovered_verdict.reason == "last_alert_unknown"
    assert persist.read_latest_tick(tmp_path)["tick_id"] == "recovered"


def test_stale_view_definition_is_repaired_on_connect(
    tmp_path: Path, monkeypatch
) -> None:
    base = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(persist, "utc_now", lambda: base)
    persist.run_tick(tmp_path, tick_id="a", noop=True)
    monkeypatch.setattr(persist, "utc_now", lambda: base + timedelta(hours=1))
    persist.run_tick(tmp_path, tick_id="b", noop=True)

    raw = sqlite3.connect(str(db.db_path(tmp_path)))
    try:
        raw.execute("DROP VIEW IF EXISTS latest")
        raw.execute(_STALE_VIEW_SQL)
        raw.commit()
        # A view ordered by time picks the earliest tick; the canonical view must
        # be restored so the newest seq wins.
        assert raw.execute("SELECT tick_id FROM latest").fetchone()[0] == "a"
    finally:
        raw.close()

    assert persist.read_latest_tick(tmp_path)["tick_id"] == "b"


# --- contention and a real kill -----------------------------------------


def test_second_writer_under_held_lock_fails_and_leaves_no_partial_row(
    tmp_path: Path, holding_writer
) -> None:
    persist.run_tick(tmp_path, tick_id="committed", noop=True)
    with holding_writer(tmp_path, "holder", seconds=8):
        with pytest.raises(sqlite3.OperationalError) as excinfo:
            persist.run_tick(tmp_path, tick_id="contender", noop=True)
    assert not isinstance(excinfo.value, StoreCorruptError)
    text = str(excinfo.value).lower()
    assert "locked" in text or "busy" in text
    assert {row["tick_id"] for row in _rows(tmp_path)} == {"committed"}


def test_stale_view_restore_under_a_live_writer_reports_contention(
    tmp_path: Path, holding_writer
) -> None:
    """A lock seen while bringing the schema up to date is contention, not
    corruption: the caller retries, it does not run `repair`."""
    persist.run_tick(tmp_path, tick_id="a", noop=True)
    raw = sqlite3.connect(str(db.db_path(tmp_path)))
    try:
        raw.execute("DROP VIEW IF EXISTS latest")
        raw.execute(_STALE_VIEW_SQL)
        raw.commit()
    finally:
        raw.close()

    with holding_writer(tmp_path, "holder", seconds=8):
        with pytest.raises(sqlite3.OperationalError) as excinfo:
            db.connect(tmp_path)
    assert not isinstance(excinfo.value, StoreCorruptError)
    assert not isinstance(excinfo.value, StoreUnavailableError)
    text = str(excinfo.value).lower()
    assert "locked" in text or "busy" in text


_RUNNING_TICK_SOURCE = (
    "import sys, time\n"
    "from pathlib import Path\n"
    "from tools.review_orchestrator import db, persist\n"
    "state, tick_id = Path(sys.argv[1]), sys.argv[2]\n"
    "started = persist.utc_now()\n"
    "conn = db.connect(state)\n"
    "db.start_tick(\n"
    "    conn,\n"
    "    tick_id,\n"
    "    started.isoformat(),\n"
    "    cutoff_iso=(started - persist.ABANDONED_AFTER).isoformat(),\n"
    ")\n"
    "print('READY', flush=True)\n"
    "time.sleep(120)\n"
)


def test_sigkill_between_transactions_leaves_a_running_row(tmp_path: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    proc = subprocess.Popen(
        [sys.executable, "-c", _RUNNING_TICK_SOURCE, str(tmp_path), "killed-mid-flight"],
        env=env,
        cwd=str(_REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "READY"
        proc.kill()
        proc.wait(timeout=15)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=15)

    outcomes = {row["tick_id"]: row["outcome"] for row in _rows(tmp_path)}
    assert outcomes == {"killed-mid-flight": "running"}

    later = datetime.now(timezone.utc) + timedelta(minutes=41)
    verdict = deadman.evaluate_deadman(tmp_path, max_age_minutes=40, now=later)
    assert verdict.reason == "attempt_stale"

    assert persist.run_tick(tmp_path, tick_id="after-kill", noop=True).overlap is True
