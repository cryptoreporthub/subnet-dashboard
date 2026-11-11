"""One-command v1a exam: stale tick, fresh tick, empty dir, last_alert_ok false."""

from __future__ import annotations

import argparse
import json
import secrets
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.review_orchestrator.deadman import evaluate_deadman
from tools.review_orchestrator.persist import run_tick

V1A_RULES = (
    "stale_tick_41m_alerts",
    "fresh_tick_ok",
    "empty_dir_alerts",
    "last_alert_ok_false_alerts",
)


def _plant_seq_claim(state_dir: Path, seq: int, *, claimed_at: datetime | None = None) -> None:
    seq_dir = state_dir / "seq"
    seq_dir.mkdir(parents=True, exist_ok=True)
    when = claimed_at or datetime.now(timezone.utc)
    (seq_dir / f"{seq}.json").write_text(
        json.dumps({"seq": seq, "claimed_at": when.isoformat()}, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _plant_completed_tick(
    state_dir: Path,
    *,
    tick_id: str,
    completed_at: datetime,
    last_alert_ok: bool = True,
    seq: int = 1,
) -> None:
    started = completed_at - timedelta(minutes=1)
    payload = {
        "tick_id": tick_id,
        "seq": seq,
        "status": "completed",
        "noop": False,
        "overlap": False,
        "started_at": started.isoformat(),
        "completed_at": completed_at.isoformat(),
        "last_alert_ok": last_alert_ok,
    }
    ticks = state_dir / "ticks"
    ticks.mkdir(parents=True, exist_ok=True)
    (ticks / f"tick-{tick_id}.json").write_text(
        json.dumps(payload, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _plant_seq_claim(state_dir, seq)


def _check_stale_tick_41m_alerts(state_dir: Path) -> bool:
    reference = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    stale_dir = state_dir / "case_stale"
    stale_dir.mkdir(parents=True)
    completed = reference - timedelta(minutes=41)
    _plant_completed_tick(stale_dir, tick_id="stale", completed_at=completed)
    verdict = evaluate_deadman(stale_dir, max_age_minutes=40, now=reference)
    return verdict.ok is False and "stale" in verdict.reason


def _check_fresh_tick_ok(state_dir: Path) -> bool:
    fresh_dir = state_dir / "case_fresh"
    fresh_dir.mkdir(parents=True)
    run_tick(fresh_dir, tick_id="fresh", noop=False)
    verdict = evaluate_deadman(fresh_dir, max_age_minutes=40)
    return verdict.ok is True and verdict.reason == "ok"


def _check_empty_dir_alerts(state_dir: Path) -> bool:
    empty_dir = state_dir / "case_empty"
    empty_dir.mkdir(parents=True)
    reference = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    verdict = evaluate_deadman(empty_dir, max_age_minutes=40, now=reference)
    return verdict.ok is False and verdict.reason == "no_valid_completed_tick"


def _check_last_alert_ok_false_alerts(state_dir: Path) -> bool:
    bad_dir = state_dir / "case_alert_flag"
    bad_dir.mkdir(parents=True)
    reference = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    completed = reference - timedelta(minutes=1)
    _plant_completed_tick(
        bad_dir, tick_id="flagged", completed_at=completed, last_alert_ok=False
    )
    verdict = evaluate_deadman(bad_dir, max_age_minutes=40, now=reference)
    return verdict.ok is False and verdict.reason == "last_alert_ok_false"


def run_exam(state_dir: Path) -> int:
    checks = {
        V1A_RULES[0]: _check_stale_tick_41m_alerts(state_dir),
        V1A_RULES[1]: _check_fresh_tick_ok(state_dir),
        V1A_RULES[2]: _check_empty_dir_alerts(state_dir),
        V1A_RULES[3]: _check_last_alert_ok_false_alerts(state_dir),
    }

    all_ok = True
    for rule in V1A_RULES:
        ok = checks[rule]
        all_ok = all_ok and ok
        status = "PASS" if ok else "FAIL"
        print(f"v1a rule {rule}: {status}")
    overall = "PASS" if all_ok else "FAIL"
    print(f"v1a exam: {overall}")
    return 0 if all_ok else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Review orchestrator v1a exam")
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

    state_dir = Path(tempfile.mkdtemp(prefix="review-orchestrator-v1a-exam-"))
    try:
        sys.exit(run_exam(state_dir))
    finally:
        shutil.rmtree(state_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
