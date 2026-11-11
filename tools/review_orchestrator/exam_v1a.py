"""One-command v1a exam: heartbeat-only dead-man rules."""

from __future__ import annotations

import argparse
import secrets
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.review_orchestrator.deadman import evaluate_deadman
from tools.review_orchestrator.persist import _write_tick_atomically, run_tick

V1A_RULES = (
    "stale_tick_41m_alerts",
    "fresh_tick_ok",
    "missing_heartbeat_alerts",
    "last_alert_ok_false_alerts",
    "future_heartbeat_alerts",
)


def _write_heartbeat(
    state_dir: Path,
    *,
    attempt_at: datetime,
    completed_at: datetime,
    last_alert_ok: bool = True,
) -> None:
    _write_tick_atomically(
        state_dir / "heartbeat" / "latest.json",
        {
            "tick_id": "exam",
            "attempt_at": attempt_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "last_alert_ok": last_alert_ok,
        },
    )


def _check_stale_tick_41m_alerts(state_dir: Path) -> bool:
    reference = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    stale_dir = state_dir / "case_stale"
    stale_dir.mkdir(parents=True)
    old = reference - timedelta(minutes=41)
    _write_heartbeat(stale_dir, attempt_at=old, completed_at=old)
    verdict = evaluate_deadman(stale_dir, max_age_minutes=40, now=reference)
    return verdict.ok is False and verdict.reason in {"attempt_stale", "completed_stale"}


def _check_fresh_tick_ok(state_dir: Path) -> bool:
    fresh_dir = state_dir / "case_fresh"
    fresh_dir.mkdir(parents=True)
    run_tick(fresh_dir, tick_id="fresh", noop=False)
    verdict = evaluate_deadman(fresh_dir, max_age_minutes=40)
    return verdict.ok is True and verdict.reason == "ok"


def _check_missing_heartbeat_alerts(state_dir: Path) -> bool:
    empty_dir = state_dir / "case_empty"
    empty_dir.mkdir(parents=True)
    reference = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    verdict = evaluate_deadman(empty_dir, max_age_minutes=40, now=reference)
    return verdict.ok is False and verdict.reason == "heartbeat_unreadable"


def _check_last_alert_ok_false_alerts(state_dir: Path) -> bool:
    bad_dir = state_dir / "case_alert_flag"
    bad_dir.mkdir(parents=True)
    reference = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    recent = reference - timedelta(minutes=1)
    _write_heartbeat(bad_dir, attempt_at=recent, completed_at=recent, last_alert_ok=False)
    verdict = evaluate_deadman(bad_dir, max_age_minutes=40, now=reference)
    return verdict.ok is False and verdict.reason == "last_alert_failed"


def _check_future_heartbeat_alerts(state_dir: Path) -> bool:
    future_dir = state_dir / "case_future"
    future_dir.mkdir(parents=True)
    reference = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    recent = reference - timedelta(minutes=1)
    _write_heartbeat(
        future_dir,
        attempt_at=reference + timedelta(minutes=6),
        completed_at=recent,
    )
    verdict = evaluate_deadman(future_dir, max_age_minutes=40, now=reference)
    return verdict.ok is False and verdict.reason == "heartbeat_future"


def run_exam(state_dir: Path) -> int:
    checks = {
        V1A_RULES[0]: _check_stale_tick_41m_alerts(state_dir),
        V1A_RULES[1]: _check_fresh_tick_ok(state_dir),
        V1A_RULES[2]: _check_missing_heartbeat_alerts(state_dir),
        V1A_RULES[3]: _check_last_alert_ok_false_alerts(state_dir),
        V1A_RULES[4]: _check_future_heartbeat_alerts(state_dir),
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
