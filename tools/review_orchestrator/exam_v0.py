"""One-command store exam: ticks, overlap, sweep, duplicate rejection."""

from __future__ import annotations

import argparse
import secrets
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.review_orchestrator import db, persist
from tools.review_orchestrator.db import DuplicateTickIdError

V0_RULES = (
    "tick_rows_rise_in_seq_with_duration",
    "duplicate_tick_id_rejected",
    "overlap_reported_against_running_row",
    "latest_row_is_newest_seq",
    "stale_running_row_swept",
)


def _plant_running(state_dir: Path, tick_id: str, started_at: str) -> None:
    conn = db.connect(state_dir)
    try:
        conn.execute(
            "INSERT INTO ticks (tick_id, started_at, overlap) VALUES (?, ?, 0)",
            (tick_id, started_at),
        )
    finally:
        conn.close()


def _read_rows(state_dir: Path) -> list[dict]:
    """Read rows in sequence order for comparison with the known tick order."""
    conn = db.connect(state_dir)
    try:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT seq, tick_id, outcome, duration_ms FROM ticks ORDER BY seq"
            )
        ]
    finally:
        conn.close()


def _check_rows(state_dir: Path, expected_ids: list[str]) -> bool:
    rows = _read_rows(state_dir)
    ids = [row["tick_id"] for row in rows]
    seqs = [row["seq"] for row in rows]
    return (
        ids == list(expected_ids)
        and seqs == list(range(1, len(expected_ids) + 1))
        and all(
            row["outcome"] == "completed" and row["duration_ms"] is not None
            for row in rows
        )
    )


def _check_duplicate(state_dir: Path) -> bool:
    probe = state_dir / "dup_probe"
    probe.mkdir(parents=True)
    persist.run_tick(probe, tick_id="twice", noop=True)
    try:
        persist.run_tick(probe, tick_id="twice", noop=True)
    except DuplicateTickIdError:
        conn = db.connect(probe)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM ticks WHERE tick_id = 'twice'"
            ).fetchone()[0]
        finally:
            conn.close()
        return int(count) == 1
    return False


def _check_overlap(state_dir: Path) -> bool:
    probe = state_dir / "overlap_probe"
    probe.mkdir(parents=True)
    old = datetime.now(timezone.utc) - timedelta(minutes=1)
    _plant_running(probe, "holder", old.isoformat())
    result = persist.run_tick(probe, tick_id="challenger", noop=True)
    return result.overlap is True


def _check_latest(state_dir: Path, expected_tick_id: str) -> bool:
    row = persist.read_latest_tick(state_dir)
    return row is not None and row["tick_id"] == expected_tick_id


def _check_sweep(state_dir: Path) -> bool:
    probe = state_dir / "sweep_probe"
    probe.mkdir(parents=True)
    old = datetime.now(timezone.utc) - timedelta(minutes=41)
    _plant_running(probe, "killed", old.isoformat())
    result = persist.run_tick(probe, tick_id="next", noop=True)
    conn = db.connect(probe)
    try:
        outcome = conn.execute(
            "SELECT outcome FROM ticks WHERE tick_id = 'killed'"
        ).fetchone()[0]
    finally:
        conn.close()
    return result.overlap is False and outcome == "abandoned"


def run_exam(state_dir: Path) -> int:
    tick_ids = ["e1", "e2", "e3", "e4", "e5"]
    for idx, tick_id in enumerate(tick_ids):
        persist.run_tick(state_dir, tick_id=tick_id, noop=idx % 2 == 1)

    checks = {
        V0_RULES[0]: _check_rows(state_dir, tick_ids),
        V0_RULES[1]: _check_duplicate(state_dir),
        V0_RULES[2]: _check_overlap(state_dir),
        V0_RULES[3]: _check_latest(state_dir, tick_ids[-1]),
        V0_RULES[4]: _check_sweep(state_dir),
    }

    all_ok = True
    for rule in V0_RULES:
        ok = checks[rule]
        all_ok = all_ok and ok
        print(f"v0 rule {rule}: {'PASS' if ok else 'FAIL'}")
    print(f"v0 exam: {'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Review orchestrator store exam")
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="Parent store directory; exam runs in a disposable exam-<token>/ subdir",
    )
    args = parser.parse_args()

    if args.state_dir is not None:
        parent = args.state_dir.resolve()
        parent.mkdir(parents=True, exist_ok=True)
        exam_root = parent / f"exam-{secrets.token_hex(8)}"
        exam_root.mkdir(parents=True)
        try:
            sys.exit(run_exam(exam_root))
        finally:
            shutil.rmtree(exam_root, ignore_errors=True)

    state_dir = Path(tempfile.mkdtemp(prefix="review-orchestrator-v0-exam-"))
    try:
        sys.exit(run_exam(state_dir))
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
