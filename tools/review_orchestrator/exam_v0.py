"""One-command v0 exam: five alternating ticks, print pass/fail per rule."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from tools.review_orchestrator.persist import (
    create_if_absent,
    read_newest_completed_tick,
    run_tick,
)


V0_RULES = (
    "one_completed_file_per_tick",
    "create_if_absent_rejects_duplicate",
    "reader_ignores_tmp_suffix",
    "overlap_reported_when_concurrent",
    "reader_returns_newest_completed",
)


def _check_one_file_per_tick(state_dir: Path, tick_ids: list[str]) -> bool:
    ticks = state_dir / "ticks"
    for tick_id in tick_ids:
        path = ticks / f"tick-{tick_id}.json"
        if not path.is_file():
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("status") != "completed":
            return False
    return len(list(ticks.glob("tick-*.json"))) == len(tick_ids)


def _check_create_if_absent(state_dir: Path) -> bool:
    path = state_dir / "exclusive" / "exam-intent.json"
    first = create_if_absent(path, {"exam": True})
    second = create_if_absent(path, {"exam": True})
    return first is True and second is False and path.is_file()


def _check_ignore_tmp(state_dir: Path) -> bool:
    planted = state_dir / "ticks" / "planted.json.tmp"
    planted.write_text('{"status": "completed", "seq": 999999}\n', encoding="utf-8")
    newest = read_newest_completed_tick(state_dir)
    return newest is not None and newest.get("tick_id") == tick_ids[-1]


def _check_overlap(state_dir: Path) -> bool:
    overlap_dir = state_dir / "overlap_probe"
    shutil.rmtree(overlap_dir, ignore_errors=True)
    overlap_dir.mkdir(parents=True)
    barrier = threading.Barrier(2)
    outcomes: list[bool] = []

    def worker(tick_id: str) -> None:
        barrier.wait(timeout=3)
        result = run_tick(overlap_dir, tick_id=tick_id, noop=True)
        outcomes.append(result.overlap)

    threads = [
        threading.Thread(target=worker, args=("ov-a",)),
        threading.Thread(target=worker, args=("ov-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    return outcomes.count(True) == 1 and outcomes.count(False) == 1


def run_exam() -> int:
    global tick_ids
    tick_ids = ["e1", "e2", "e3", "e4", "e5"]
    state_dir = Path(tempfile.mkdtemp(prefix="review-orchestrator-v0-exam-"))
    try:
        for idx, tick_id in enumerate(tick_ids):
            noop = idx % 2 == 1
            run_tick(state_dir, tick_id=tick_id, noop=noop)

        checks = {
            V0_RULES[0]: _check_one_file_per_tick(state_dir, tick_ids),
            V0_RULES[1]: _check_create_if_absent(state_dir),
            V0_RULES[2]: _check_ignore_tmp(state_dir),
            V0_RULES[3]: _check_overlap(state_dir),
            V0_RULES[4]: (
                read_newest_completed_tick(state_dir) is not None
                and read_newest_completed_tick(state_dir)["tick_id"] == "e5"
            ),
        }

        all_ok = True
        for rule in V0_RULES:
            ok = checks[rule]
            all_ok = all_ok and ok
            status = "PASS" if ok else "FAIL"
            print(f"v0 rule {rule}: {status}")
        overall = "PASS" if all_ok else "FAIL"
        print(f"v0 exam: {overall}")
        return 0 if all_ok else 1
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


tick_ids: list[str] = []


def main() -> None:
    parser = argparse.ArgumentParser(description="Review orchestrator v0 exam")
    parser.parse_args()
    sys.exit(run_exam())


if __name__ == "__main__":
    main()
