"""Store contract tests (behavior, not implementation)."""

from __future__ import annotations

import multiprocessing as mp
import os
import secrets
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import tools.review_orchestrator.persist as persist
from tools.review_orchestrator import db
from tools.review_orchestrator.db import DuplicateTickIdError, StoreCorruptError

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
