"""v0 persist contract tests (behavior, not implementation)."""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import secrets
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import tools.review_orchestrator.persist as persist
from tools.review_orchestrator.persist import (
    DuplicateTickIdError,
    NewestTickRead,
    _validate_tick_file,
    create_if_absent,
    read_newest_completed_tick,
    read_newest_completed_tick_report,
    run_tick,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _assert_tick_file_valid(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["status"] == "completed"
    assert isinstance(data["seq"], int)
    assert data.get("started_at")
    assert data.get("completed_at")
    return data


def test_tick_completes_via_tmp_then_rename(tmp_path: Path) -> None:
    result = run_tick(tmp_path, tick_id="alpha", noop=False)
    data = _assert_tick_file_valid(result.path)
    assert data["tick_id"] == "alpha"
    assert not any(p.name.endswith(".tmp") for p in result.path.parent.iterdir())


def test_run_tick_publishes_via_os_replace_from_tmp(tmp_path: Path, monkeypatch) -> None:
    pairs: list[tuple[str, str]] = []
    real_replace = os.replace

    def spy_replace(src: os.PathLike | str, dst: os.PathLike | str) -> None:
        pairs.append((os.fspath(src), os.fspath(dst)))
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)
    result = run_tick(tmp_path, tick_id="rename", noop=False)
    assert result.path.is_file()
    assert any(src.endswith(".tmp") and dst.endswith("tick-rename.json") for src, dst in pairs)


def test_os_replace_failure_leaves_no_completed_tick_file(tmp_path: Path, monkeypatch) -> None:
    def fail_replace(_src: os.PathLike | str, _dst: os.PathLike | str) -> None:
        raise OSError("simulated rename failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated rename"):
        run_tick(tmp_path, tick_id="no-final", noop=False)
    assert not (tmp_path / "ticks" / "tick-no-final.json").is_file()


def test_mutation_run_tick_without_os_replace_fails_publish(tmp_path: Path, monkeypatch) -> None:
    def broken_write(final_path: Path, payload: dict) -> None:
        side = final_path.with_name(f"{final_path.name}.partial.tmp")
        side.parent.mkdir(parents=True, exist_ok=True)
        side.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    monkeypatch.setattr(persist, "_write_tick_atomically", broken_write)
    broken = run_tick(tmp_path, tick_id="broken", noop=False)
    assert not broken.path.is_file()

    monkeypatch.undo()
    good = run_tick(tmp_path, tick_id="good", noop=False)
    assert good.path.is_file()


def test_reader_hammer_while_tick_writes_never_see_bad_json(tmp_path: Path) -> None:
    stop = threading.Event()
    bad_parses: list[str] = []
    lock = threading.Lock()

    def writer() -> None:
        n = 0
        while not stop.is_set():
            run_tick(tmp_path, tick_id=f"hammer-{n}", noop=True)
            n += 1

    def reader() -> None:
        ticks = tmp_path / "ticks"
        while not stop.is_set():
            if not ticks.is_dir():
                continue
            for path in ticks.glob("tick-*.json"):
                if path.name.endswith(".reserve.json"):
                    continue
                try:
                    json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    with lock:
                        bad_parses.append(path.name)
            read_newest_completed_tick_report(tmp_path)

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for thread in threads:
        thread.start()
    threads[0].join(timeout=2.0)
    stop.set()
    for thread in threads:
        thread.join(timeout=5)
    assert not bad_parses


def test_create_if_absent_exclusive(tmp_path: Path) -> None:
    target = tmp_path / "exclusive" / "intent-a.json"
    assert create_if_absent(target, {"kind": "intent-a"}) is True
    assert target.is_file()
    assert create_if_absent(target, {"kind": "intent-a"}) is False


def test_create_if_absent_barrier_race_never_double_winner(tmp_path: Path) -> None:
    for round_idx in range(40):
        target = tmp_path / "exclusive" / f"round-{round_idx}.json"
        barrier = threading.Barrier(16)
        wins: list[bool] = []
        lock = threading.Lock()

        def worker() -> None:
            barrier.wait(timeout=3)
            ok = create_if_absent(target, {"round": round_idx})
            with lock:
                wins.append(ok)

        threads = [threading.Thread(target=worker) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        assert wins.count(True) == 1, f"round {round_idx}"


def _barrier_seq_worker(store: str, barrier: mp.Barrier, out: mp.Queue) -> None:
    barrier.wait(timeout=5)
    result = run_tick(Path(store), tick_id=secrets.token_hex(4), noop=True)
    out.put(result.seq)


def test_allocate_seq_unique_under_barrier_processes(tmp_path: Path) -> None:
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(4)
    out: mp.Queue = ctx.Queue()
    store = str(tmp_path)
    procs = [
        ctx.Process(target=_barrier_seq_worker, args=(store, barrier, out))
        for _ in range(4)
    ]
    for proc in procs:
        proc.start()
    for proc in procs:
        proc.join(timeout=15)
    seqs = [out.get_nowait() for _ in range(4)]
    assert len(set(seqs)) == 4


def test_allocate_seq_unique_under_parallel_ticks(tmp_path: Path) -> None:
    barrier = threading.Barrier(8)
    seqs: list[int] = []
    lock = threading.Lock()

    def worker(idx: int) -> None:
        barrier.wait(timeout=3)
        result = run_tick(tmp_path, tick_id=f"par-{idx}", noop=True)
        with lock:
            seqs.append(result.seq)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert len(seqs) == 8
    assert len(set(seqs)) == 8


def test_reader_ignores_planted_tmp_and_bad_json(tmp_path: Path) -> None:
    ticks = tmp_path / "ticks"
    ticks.mkdir(parents=True)
    (ticks / "decoy.json.tmp").write_text('{"status": "completed"}\n', encoding="utf-8")
    (ticks / "planted.json").write_text(
        '{"tick_id": "planted", "seq": 999999, "status": "completed", '
        '"started_at": "2020-01-01T00:00:00+00:00", "completed_at": "2030-01-01T00:00:00+00:00"}\n',
        encoding="utf-8",
    )
    run_tick(tmp_path, tick_id="real", noop=False)
    report = read_newest_completed_tick_report(tmp_path)
    assert report.tick is not None
    assert report.tick["tick_id"] == "real"
    assert "planted.json:bad_filename" in report.skipped


def test_validate_rejects_tick_id_filename_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "tick-alpha.json"
    path.write_text(
        '{"tick_id": "beta", "seq": 1, "status": "completed", '
        '"started_at": "2020-01-01T00:00:00+00:00", "completed_at": "2020-01-02T00:00:00+00:00"}\n',
        encoding="utf-8",
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    _, err = _validate_tick_file(path, data)
    assert err == "tick-alpha.json:tick_id_mismatch"


def test_validate_rejects_start_after_end(tmp_path: Path) -> None:
    path = tmp_path / "tick-alpha.json"
    path.write_text(
        '{"tick_id": "alpha", "seq": 1, "status": "completed", '
        '"started_at": "2022-01-02T00:00:00+00:00", "completed_at": "2022-01-01T00:00:00+00:00"}\n',
        encoding="utf-8",
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    _, err = _validate_tick_file(path, data)
    assert err == "tick-alpha.json:start_after_end"


def test_validate_rejects_not_completed_status(tmp_path: Path) -> None:
    path = tmp_path / "tick-alpha.json"
    path.write_text(
        '{"tick_id": "alpha", "seq": 1, "status": "running", '
        '"started_at": "2020-01-01T00:00:00+00:00", "completed_at": "2020-01-02T00:00:00+00:00"}\n',
        encoding="utf-8",
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    _, err = _validate_tick_file(path, data)
    assert err == "tick-alpha.json:not_completed"


def test_mutation_reader_accepts_unvalidated_planted_json(tmp_path: Path, monkeypatch) -> None:
    ticks = tmp_path / "ticks"
    ticks.mkdir(parents=True)
    run_tick(tmp_path, tick_id="good", noop=False)
    (ticks / "planted.json").write_text(
        '{"tick_id": "planted", "seq": 999999, "status": "completed", '
        '"started_at": "2020-01-01T00:00:00+00:00", "completed_at": "2030-01-01T00:00:00+00:00"}\n',
        encoding="utf-8",
    )

    def naive_newest(state_dir: Path) -> NewestTickRead:
        best = None
        best_seq = -1
        for path in (state_dir / "ticks").glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            seq = int(data.get("seq", 0))
            if seq > best_seq:
                best_seq = seq
                best = data
        return NewestTickRead(tick=best, skipped=())

    monkeypatch.setattr(persist, "read_newest_completed_tick_report", naive_newest)
    broken = read_newest_completed_tick(tmp_path)
    assert broken is not None and broken["tick_id"] == "planted"

    monkeypatch.undo()
    fixed = read_newest_completed_tick(tmp_path)
    assert fixed is not None and fixed["tick_id"] == "good"


def test_overlap_against_planted_in_flight_holder(tmp_path: Path) -> None:
    active = tmp_path / "active" / "in-flight.json"
    assert create_if_absent(
        active,
        {
            "tick_id": "holder",
            "started_at": "2020-01-01T00:00:00+00:00",
            "owner_token": "holder-token",
        },
    )
    result = run_tick(tmp_path, tick_id="challenger", noop=True)
    assert result.overlap is True
    assert result.overlap_with == "holder"


def test_concurrent_duplicate_tick_id_rejects_loser(tmp_path: Path) -> None:
    barrier = threading.Barrier(2)
    successes: list = []
    rejected: list[DuplicateTickIdError] = []

    def worker() -> None:
        barrier.wait(timeout=3)
        try:
            successes.append(run_tick(tmp_path, tick_id="dup-id", noop=True))
        except DuplicateTickIdError as exc:
            rejected.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert len(successes) == 1
    assert len(rejected) == 1
    assert (tmp_path / "ticks" / "tick-dup-id.json").is_file()


def test_in_flight_release_requires_owner_token_not_tick_id(tmp_path: Path) -> None:
    active = tmp_path / "active" / "in-flight.json"
    create_if_absent(
        active,
        {
            "tick_id": "reused-id",
            "started_at": "2020-01-01T00:00:00+00:00",
            "owner_token": "holder-token",
        },
    )
    persist._release_in_flight(tmp_path, "reused-id")
    assert active.is_file()
    persist._release_in_flight(tmp_path, "holder-token")
    assert not active.is_file()


def test_concurrent_ticks_barrier_reports_at_most_one_overlap(tmp_path: Path) -> None:
    barrier = threading.Barrier(2)
    results: list = []
    errors: list[BaseException] = []

    def worker(tick_id: str) -> None:
        try:
            barrier.wait(timeout=3)
            results.append(run_tick(tmp_path, tick_id=tick_id, noop=True))
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=("con-a",)),
        threading.Thread(target=worker, args=("con-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not errors
    assert len(results) == 2
    assert sum(1 for r in results if r.overlap) <= 1


def test_sequential_ticks_do_not_report_overlap(tmp_path: Path) -> None:
    first = run_tick(tmp_path, tick_id="one", noop=False)
    second = run_tick(tmp_path, tick_id="two", noop=False)
    assert first.overlap is False
    assert second.overlap is False


def test_reader_returns_newest_by_seq_then_completed_at_tiebreak(tmp_path: Path) -> None:
    ticks = tmp_path / "ticks"
    ticks.mkdir(parents=True)
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    low = {
        "tick_id": "low",
        "seq": 1,
        "status": "completed",
        "noop": False,
        "overlap": False,
        "started_at": t0.isoformat(),
        "completed_at": (t0 + timedelta(hours=2)).isoformat(),
    }
    high = {
        "tick_id": "high",
        "seq": 10,
        "status": "completed",
        "noop": False,
        "overlap": False,
        "started_at": t0.isoformat(),
        "completed_at": (t0 + timedelta(hours=1)).isoformat(),
    }
    (ticks / "tick-low.json").write_text(json.dumps(low) + "\n", encoding="utf-8")
    (ticks / "tick-high.json").write_text(json.dumps(high) + "\n", encoding="utf-8")
    newest = read_newest_completed_tick(tmp_path)
    assert newest is not None
    assert newest["tick_id"] == "high"


def test_reader_skips_forged_far_future_completed_at(tmp_path: Path) -> None:
    ticks = tmp_path / "ticks"
    ticks.mkdir(parents=True)
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    forged = {
        "tick_id": "forged",
        "seq": 999,
        "status": "completed",
        "noop": False,
        "overlap": False,
        "started_at": "2020-01-01T00:00:00+00:00",
        "completed_at": "2030-06-01T00:00:00+00:00",
    }
    good = {
        "tick_id": "good",
        "seq": 2,
        "status": "completed",
        "noop": False,
        "overlap": False,
        "started_at": t0.isoformat(),
        "completed_at": t0.isoformat(),
    }
    (ticks / "tick-forged.json").write_text(json.dumps(forged) + "\n", encoding="utf-8")
    (ticks / "tick-good.json").write_text(json.dumps(good) + "\n", encoding="utf-8")
    report = read_newest_completed_tick_report(tmp_path)
    assert report.tick is not None
    assert report.tick["tick_id"] == "good"
    assert any("completed_at_in_future" in s for s in report.skipped)


def test_reader_skips_clock_step_ahead_completed_at(tmp_path: Path) -> None:
    ticks = tmp_path / "ticks"
    ticks.mkdir(parents=True)
    reference = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    ahead = {
        "tick_id": "ahead",
        "seq": 50,
        "status": "completed",
        "noop": False,
        "overlap": False,
        "started_at": "2026-03-01T12:00:00+00:00",
        "completed_at": "2026-03-01T12:10:00+00:00",
    }
    ok = {
        "tick_id": "ok",
        "seq": 3,
        "status": "completed",
        "noop": False,
        "overlap": False,
        "started_at": "2026-03-01T11:00:00+00:00",
        "completed_at": "2026-03-01T11:30:00+00:00",
    }
    (ticks / "tick-ahead.json").write_text(json.dumps(ahead) + "\n", encoding="utf-8")
    (ticks / "tick-ok.json").write_text(json.dumps(ok) + "\n", encoding="utf-8")
    report = read_newest_completed_tick_report(tmp_path, now=reference)
    assert report.tick is not None
    assert report.tick["tick_id"] == "ok"
    assert any("completed_at_in_future" in s for s in report.skipped)


def test_mutation_order_by_completed_at_only_picks_wrong_newest(tmp_path: Path, monkeypatch) -> None:
    ticks = tmp_path / "ticks"
    ticks.mkdir(parents=True)
    t0 = datetime(2026, 6, 1, tzinfo=timezone.utc)
    (ticks / "tick-low-seq-newer.json").write_text(
        json.dumps(
            {
                "tick_id": "low-seq-newer",
                "seq": 1,
                "status": "completed",
                "noop": False,
                "overlap": False,
                "started_at": t0.isoformat(),
                "completed_at": (t0 + timedelta(hours=2)).isoformat(),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (ticks / "tick-high-seq-older.json").write_text(
        json.dumps(
            {
                "tick_id": "high-seq-older",
                "seq": 50,
                "status": "completed",
                "noop": False,
                "overlap": False,
                "started_at": t0.isoformat(),
                "completed_at": (t0 + timedelta(hours=1)).isoformat(),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def sort_by_completed_at_only(state_dir: Path) -> NewestTickRead:
        best = None
        best_at: datetime | None = None
        for path in (state_dir / "ticks").glob("tick-*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            completed = persist._parse_utc_iso(data["completed_at"])
            assert completed is not None
            if best_at is None or completed > best_at:
                best_at = completed
                best = data
        return NewestTickRead(tick=best, skipped=())

    monkeypatch.setattr(persist, "read_newest_completed_tick_report", sort_by_completed_at_only)
    assert read_newest_completed_tick(tmp_path)["tick_id"] == "low-seq-newer"

    monkeypatch.undo()
    assert read_newest_completed_tick(tmp_path)["tick_id"] == "high-seq-older"


def test_malformed_tick_skipped_without_crash(tmp_path: Path) -> None:
    ticks = tmp_path / "ticks"
    ticks.mkdir(parents=True)
    (ticks / "tick-bad.json").write_text(
        '{"tick_id": "bad", "seq": null, "status": "completed", '
        '"started_at": "2020-01-01T00:00:00+00:00", "completed_at": "2020-01-02T00:00:00+00:00"}\n',
        encoding="utf-8",
    )
    run_tick(tmp_path, tick_id="good", noop=False)
    report = read_newest_completed_tick_report(tmp_path)
    assert report.tick is not None
    assert report.tick["tick_id"] == "good"
    assert any("bad_seq" in item for item in report.skipped)


def test_in_flight_marker_released_when_tick_write_fails(tmp_path: Path, monkeypatch) -> None:
    def boom(_final: Path, _payload: dict) -> None:
        raise OSError("simulated write failure")

    monkeypatch.setattr(persist, "_write_tick_atomically", boom)
    with pytest.raises(OSError, match="simulated"):
        run_tick(tmp_path, tick_id="fail", noop=False)

    assert not (tmp_path / "active" / "in-flight.json").is_file()
    monkeypatch.undo()
    follow = run_tick(tmp_path, tick_id="after", noop=False)
    assert follow.overlap is False


def test_mutation_stale_in_flight_after_write_failure(tmp_path: Path, monkeypatch) -> None:
    real_write = persist._write_tick_atomically

    def boom(_final: Path, payload: dict) -> None:
        if payload.get("tick_id") == "fail":
            raise OSError("simulated write failure")
        real_write(_final, payload)

    def noop_release(_state_dir: Path, _tick_id: str) -> None:
        return None

    monkeypatch.setattr(persist, "_write_tick_atomically", boom)
    monkeypatch.setattr(persist, "_release_in_flight", noop_release)
    with pytest.raises(OSError):
        run_tick(tmp_path, tick_id="fail", noop=False)
    assert (tmp_path / "active" / "in-flight.json").is_file()
    blocked = run_tick(tmp_path, tick_id="next", noop=True)
    assert blocked.overlap is True

    monkeypatch.undo()
    stale = tmp_path / "active" / "in-flight.json"
    if stale.is_file():
        stale.unlink()
    ok = run_tick(tmp_path, tick_id="after", noop=False)
    assert ok.overlap is False


def test_durable_seq_increments_across_subprocess(tmp_path: Path) -> None:
    run_tick(tmp_path, tick_id="parent", noop=False)
    store = str(tmp_path)
    code = f"""
from pathlib import Path
from tools.review_orchestrator.persist import run_tick
run_tick(Path({store!r}), tick_id="child", noop=False)
"""
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT)}
    subprocess.run([sys.executable, "-c", code], check=True, env=env, cwd=str(_REPO_ROOT))
    seqs = sorted(json.loads(p.read_text(encoding="utf-8"))["seq"] for p in (tmp_path / "ticks").glob("tick-*.json"))
    assert seqs == [1, 2]


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
    children = list(parent.iterdir())
    assert children == []
