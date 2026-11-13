"""One-command v0 exam: five alternating ticks, print pass/fail per rule."""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import sys
import tempfile
from pathlib import Path

from tools.review_orchestrator.persist import (
    _active_path,
    _parse_utc_iso,
    create_if_absent,
    read_newest_completed_tick_report,
    run_tick,
)


V0_RULES = (
    "tick_start_end_and_rising_seq",
    "create_if_absent_rejects_duplicate",
    "reader_ignores_invalid_files",
    "overlap_reported_against_holder",
    "reader_returns_newest_completed",
)


def _check_tick_start_end_and_rising_seq(state_dir: Path, tick_ids: list[str]) -> bool:
    ticks = state_dir / "ticks"
    prev_seq: int | None = None
    for tick_id in tick_ids:
        path = ticks / f"tick-{tick_id}.json"
        if not path.is_file():
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        started = _parse_utc_iso(data.get("started_at"))
        completed = _parse_utc_iso(data.get("completed_at"))
        seq = data.get("seq")
        if started is None or completed is None or not isinstance(seq, int):
            return False
        if started > completed:
            return False
        if prev_seq is not None and seq <= prev_seq:
            return False
        prev_seq = seq
    return True


def _check_create_if_absent(state_dir: Path) -> bool:
    path = state_dir / "exclusive" / "exam-intent.json"
    first = create_if_absent(path, {"exam": True})
    second = create_if_absent(path, {"exam": True})
    return first is True and second is False and path.is_file()


def _check_reader_ignores_invalid(state_dir: Path, expected_tick_id: str) -> bool:
    ticks = state_dir / "ticks"
    ticks.mkdir(parents=True, exist_ok=True)
    (ticks / "planted.json.tmp").write_text(
        '{"status": "completed", "seq": 999999, "tick_id": "fake", '
        '"started_at": "2020-01-01T00:00:00+00:00", "completed_at": "2020-01-02T00:00:00+00:00"}\n',
        encoding="utf-8",
    )
    (ticks / "planted.json").write_text(
        '{"tick_id": "planted", "seq": 999999, "status": "completed", '
        '"started_at": "2020-01-01T00:00:00+00:00", "completed_at": "2030-01-01T00:00:00+00:00"}\n',
        encoding="utf-8",
    )
    (ticks / "tick-bad.json").write_text(
        '{"tick_id": "bad", "seq": null, "status": "completed", '
        '"started_at": "2020-01-01T00:00:00+00:00", "completed_at": "2020-01-02T00:00:00+00:00"}\n',
        encoding="utf-8",
    )
    report = read_newest_completed_tick_report(state_dir)
    return (
        report.tick is not None
        and report.tick.get("tick_id") == expected_tick_id
        and any("bad_filename" in s for s in report.skipped)
        and any("bad_seq" in s for s in report.skipped)
    )


def _check_overlap_against_holder(state_dir: Path) -> bool:
    probe = state_dir / "overlap_probe"
    shutil.rmtree(probe, ignore_errors=True)
    probe.mkdir(parents=True)
    active = _active_path(probe)
    holder_created = create_if_absent(
        active,
        {"tick_id": "holder", "started_at": "2020-01-01T00:00:00+00:00"},
    )
    if not holder_created:
        return False
    second = run_tick(probe, tick_id="challenger", noop=True)
    return second.overlap is True and second.overlap_with == "holder"


def _check_reader_newest(state_dir: Path, expected_tick_id: str) -> bool:
    report = read_newest_completed_tick_report(state_dir)
    return report.tick is not None and report.tick.get("tick_id") == expected_tick_id


def run_exam(state_dir: Path) -> int:
    tick_ids = ["e1", "e2", "e3", "e4", "e5"]
    for idx, tick_id in enumerate(tick_ids):
        noop = idx % 2 == 1
        run_tick(state_dir, tick_id=tick_id, noop=noop)

    checks = {
        V0_RULES[0]: _check_tick_start_end_and_rising_seq(state_dir, tick_ids),
        V0_RULES[1]: _check_create_if_absent(state_dir),
        V0_RULES[2]: _check_reader_ignores_invalid(state_dir, tick_ids[-1]),
        V0_RULES[3]: _check_overlap_against_holder(state_dir),
        V0_RULES[4]: _check_reader_newest(state_dir, tick_ids[-1]),
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Review orchestrator v0 exam")
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
