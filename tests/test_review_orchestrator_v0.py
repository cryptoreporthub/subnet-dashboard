"""v0 persist contract tests (behavior, not implementation)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import tools.review_orchestrator.persist as persist
from tools.review_orchestrator.persist import (
    NewestTickRead,
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


def test_mutation_plain_write_skips_atomic_rename(tmp_path: Path, monkeypatch) -> None:
    def broken_write(final_path: Path, payload: dict) -> None:
        side = final_path.with_name(f"{final_path.name}.partial.tmp")
        side.parent.mkdir(parents=True, exist_ok=True)
        side.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    monkeypatch.setattr(persist, "_write_tick_atomically", broken_write)
    broken = run_tick(tmp_path, tick_id="broken", noop=False)
    assert not broken.path.is_file(), "broken write should not publish tick-*.json"

    monkeypatch.undo()
    good = run_tick(tmp_path, tick_id="good", noop=False)
    assert good.path.is_file()


def test_create_if_absent_exclusive(tmp_path: Path) -> None:
    target = tmp_path / "exclusive" / "intent-a.json"
    assert create_if_absent(target, {"kind": "intent-a"}) is True
    assert target.is_file()
    assert create_if_absent(target, {"kind": "intent-a"}) is False


def test_create_if_absent_exactly_one_winner_under_race(tmp_path: Path) -> None:
    target = tmp_path / "exclusive" / "race.json"
    wins: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        ok = create_if_absent(target, {"n": 1})
        with lock:
            wins.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert wins.count(True) == 1


def test_mutation_check_then_write_can_double_create(tmp_path: Path, monkeypatch) -> None:
    double_seen = False

    def racy_create(path: Path, payload: dict) -> bool:
        if path.exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        return True

    def race_once() -> int:
        target = tmp_path / "exclusive" / "once.json"
        if target.exists():
            target.unlink()
        barrier = threading.Barrier(8)
        wins: list[bool] = []

        def worker() -> None:
            barrier.wait(timeout=2)
            wins.append(racy_create(target, {"x": 1}))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        return wins.count(True)

    monkeypatch.setattr(persist, "create_if_absent", racy_create)
    for _ in range(30):
        if race_once() > 1:
            double_seen = True
            break
    assert double_seen, "check-then-write should allow more than one winner"

    monkeypatch.undo()
    target = tmp_path / "exclusive" / "good.json"
    assert sum(create_if_absent(target, {"i": i}) for i in range(8)) == 1


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
    assert create_if_absent(active, {"tick_id": "holder", "started_at": "2020-01-01T00:00:00+00:00"})
    result = run_tick(tmp_path, tick_id="challenger", noop=True)
    assert result.overlap is True
    assert result.overlap_with == "holder"


def test_sequential_ticks_do_not_report_overlap(tmp_path: Path) -> None:
    first = run_tick(tmp_path, tick_id="one", noop=False)
    second = run_tick(tmp_path, tick_id="two", noop=False)
    assert first.overlap is False
    assert second.overlap is False


def test_reader_returns_newest_by_completed_at_not_process_seq(tmp_path: Path) -> None:
    ticks = tmp_path / "ticks"
    ticks.mkdir(parents=True)
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    old = {
        "tick_id": "old",
        "seq": 99,
        "status": "completed",
        "noop": False,
        "overlap": False,
        "overlap_with": None,
        "started_at": t0.isoformat(),
        "completed_at": (t0 + timedelta(seconds=10)).isoformat(),
    }
    new = {
        "tick_id": "new",
        "seq": 1,
        "status": "completed",
        "noop": False,
        "overlap": False,
        "overlap_with": None,
        "started_at": (t0 + timedelta(seconds=20)).isoformat(),
        "completed_at": (t0 + timedelta(seconds=30)).isoformat(),
    }
    (ticks / "tick-old.json").write_text(json.dumps(old) + "\n", encoding="utf-8")
    (ticks / "tick-new.json").write_text(json.dumps(new) + "\n", encoding="utf-8")
    newest = read_newest_completed_tick(tmp_path)
    assert newest is not None
    assert newest["tick_id"] == "new"


def test_mutation_order_by_seq_only_picks_wrong_newest(tmp_path: Path, monkeypatch) -> None:
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
                "overlap_with": None,
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
                "overlap_with": None,
                "started_at": t0.isoformat(),
                "completed_at": (t0 + timedelta(hours=1)).isoformat(),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def sort_by_seq_only(state_dir: Path) -> NewestTickRead:
        best = None
        best_seq = -1
        for path in (state_dir / "ticks").glob("tick-*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            seq = int(data["seq"])
            if seq > best_seq:
                best_seq = seq
                best = data
        return NewestTickRead(tick=best, skipped=())

    monkeypatch.setattr(persist, "read_newest_completed_tick_report", sort_by_seq_only)
    assert read_newest_completed_tick(tmp_path)["tick_id"] == "high-seq-older"

    monkeypatch.undo()
    assert read_newest_completed_tick(tmp_path)["tick_id"] == "low-seq-newer"


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
