"""v0 persist contract tests (behavior, not implementation)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from tools.review_orchestrator.persist import (
    create_if_absent,
    read_newest_completed_tick,
    run_tick,
)


def test_tick_completes_via_tmp_then_rename(tmp_path: Path) -> None:
    result = run_tick(tmp_path, tick_id="alpha", noop=False)
    assert result.path.is_file()
    assert not any(p.suffix.endswith(".tmp") for p in result.path.parent.iterdir())
    data = json.loads(result.path.read_text(encoding="utf-8"))
    assert data["status"] == "completed"
    assert data["tick_id"] == "alpha"


def test_create_if_absent_exclusive(tmp_path: Path) -> None:
    target = tmp_path / "exclusive" / "intent-a.json"
    assert create_if_absent(target, {"kind": "intent-a"}) is True
    assert target.is_file()
    assert create_if_absent(target, {"kind": "intent-a"}) is False


def test_reader_ignores_planted_tmp(tmp_path: Path) -> None:
    ticks = tmp_path / "ticks"
    ticks.mkdir(parents=True)
    planted = ticks / "decoy.json.tmp"
    planted.write_text('{"status": "completed", "seq": 99999}\n', encoding="utf-8")
    run_tick(tmp_path, tick_id="real", noop=False)
    newest = read_newest_completed_tick(tmp_path)
    assert newest is not None
    assert newest["tick_id"] == "real"


def test_concurrent_ticks_report_overlap(tmp_path: Path) -> None:
    barrier = threading.Barrier(2)
    results: list = []
    errors: list[BaseException] = []

    def worker(tick_id: str) -> None:
        try:
            barrier.wait(timeout=3)
            results.append(run_tick(tmp_path, tick_id=tick_id, noop=True))
        except BaseException as exc:
            errors.append(exc)

    t1 = threading.Thread(target=worker, args=("t-one",))
    t2 = threading.Thread(target=worker, args=("t-two",))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert not errors
    assert len(results) == 2
    overlaps = [r for r in results if r.overlap]
    assert len(overlaps) == 1
    non = [r for r in results if not r.overlap]
    assert len(non) == 1


def test_reader_returns_newest_completed_tick(tmp_path: Path) -> None:
    run_tick(tmp_path, tick_id="old", noop=False)
    time.sleep(0.002)
    run_tick(tmp_path, tick_id="new", noop=False)
    newest = read_newest_completed_tick(tmp_path)
    assert newest is not None
    assert newest["tick_id"] == "new"
