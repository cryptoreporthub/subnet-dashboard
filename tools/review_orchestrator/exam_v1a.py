"""One-command v1a exam: dead-man rules over the store's latest row."""

from __future__ import annotations

import argparse
import secrets
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.review_orchestrator import db, persist
from tools.review_orchestrator.deadman import evaluate_deadman

V1A_RULES = (
    "fresh_tick_alert_unknown",
    "missing_store_alerts",
    "stale_attempt_alerts",
    "completed_stale_alerts",
    "future_started_at_alerts",
    "failing_tick_alerts",
)


def _plant(
    state_dir: Path,
    tick_id: str,
    started_at: datetime,
    *,
    duration_ms: int | None = None,
) -> None:
    conn = db.connect(state_dir)
    try:
        if duration_ms is None:
            conn.execute(
                "INSERT INTO ticks (tick_id, started_at, overlap) VALUES (?, ?, 0)",
                (tick_id, started_at.isoformat()),
            )
        else:
            conn.execute(
                "INSERT INTO ticks (tick_id, started_at, duration_ms, outcome, noop, overlap) "
                "VALUES (?, ?, ?, 'completed', 0, 0)",
                (tick_id, started_at.isoformat(), duration_ms),
            )
    finally:
        conn.close()


def _check_fresh_tick_alert_unknown(state_dir: Path) -> bool:
    case = state_dir / "case_fresh"
    case.mkdir(parents=True)
    persist.run_tick(case, tick_id="fresh", noop=False)
    verdict = evaluate_deadman(case, max_age_minutes=40)
    return verdict.ok is False and verdict.reason == "last_alert_unknown"


def _check_missing_store_alerts(state_dir: Path) -> bool:
    case = state_dir / "case_empty"
    if case.exists():
        return False
    reference = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    verdict = evaluate_deadman(case, max_age_minutes=40, now=reference)
    return (
        verdict.ok is False
        and verdict.reason == "heartbeat_unreadable"
        and not case.exists()
    )


def _check_stale_attempt_alerts(state_dir: Path) -> bool:
    case = state_dir / "case_stale"
    case.mkdir(parents=True)
    reference = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    _plant(case, "killed", reference - timedelta(minutes=41))
    verdict = evaluate_deadman(case, max_age_minutes=40, now=reference)
    return verdict.ok is False and verdict.reason == "attempt_stale"


def _check_completed_stale_alerts(state_dir: Path) -> bool:
    case = state_dir / "case_completed_stale"
    case.mkdir(parents=True)
    reference = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    _plant(case, "old", reference - timedelta(minutes=41), duration_ms=1000)
    verdict = evaluate_deadman(case, max_age_minutes=40, now=reference)
    return verdict.ok is False and verdict.reason == "completed_stale"


def _check_future_started_at_alerts(state_dir: Path) -> bool:
    case = state_dir / "case_future"
    case.mkdir(parents=True)
    reference = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    _plant(case, "future", reference + timedelta(minutes=6))
    verdict = evaluate_deadman(case, max_age_minutes=40, now=reference)
    return verdict.ok is False and verdict.reason == "heartbeat_future"


def _check_failing_tick_alerts(state_dir: Path) -> bool:
    case = state_dir / "case_failed"
    case.mkdir(parents=True)
    reference = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    conn = db.connect(case)
    try:
        conn.execute(
            "INSERT INTO ticks (tick_id, started_at, duration_ms, outcome, noop, overlap) "
            "VALUES ('failing', ?, 5, 'failed', 0, 0)",
            ((reference - timedelta(minutes=1)).isoformat(),),
        )
    finally:
        conn.close()
    verdict = evaluate_deadman(case, max_age_minutes=40, now=reference)
    return verdict.ok is False and verdict.reason == "tick_failed"


def run_exam(state_dir: Path) -> int:
    checks = {
        V1A_RULES[0]: _check_fresh_tick_alert_unknown(state_dir),
        V1A_RULES[1]: _check_missing_store_alerts(state_dir),
        V1A_RULES[2]: _check_stale_attempt_alerts(state_dir),
        V1A_RULES[3]: _check_completed_stale_alerts(state_dir),
        V1A_RULES[4]: _check_future_started_at_alerts(state_dir),
        V1A_RULES[5]: _check_failing_tick_alerts(state_dir),
    }

    all_ok = True
    for rule in V1A_RULES:
        ok = checks[rule]
        all_ok = all_ok and ok
        print(f"v1a rule {rule}: {'PASS' if ok else 'FAIL'}")
    print(f"v1a exam: {'PASS' if all_ok else 'FAIL'}")
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
