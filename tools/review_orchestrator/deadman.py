"""v1a dead-man check: read the store's `latest` row only.

The reader never writes a heartbeat, so it cannot roll one back. It needs write
access to the state directory: the store is WAL, and a reader must be able to
create or write the `-shm` wal-index beside the database. Run it with the same
filesystem access as the writer.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.review_orchestrator import db
from tools.review_orchestrator.persist import parse_utc_iso, utc_now

_FUTURE_SLACK = timedelta(minutes=5)


@dataclass(frozen=True)
class DeadmanVerdict:
    ok: bool
    reason: str


def _is_future(ts: datetime, reference: datetime) -> bool:
    return ts > reference + _FUTURE_SLACK


def _derived_completed_at(started_at: datetime, duration_ms: object) -> datetime | None:
    if duration_ms is None:
        return None
    return started_at + timedelta(milliseconds=int(duration_ms))  # type: ignore[arg-type]


def _load_latest(state_dir: Path):
    state_dir = Path(state_dir)
    with db.store_lock(state_dir):
        if not db.db_path(state_dir).is_file():
            return None
        conn = db.connect_reader(state_dir)
        try:
            return db.latest_row(conn)
        finally:
            conn.close()


def _is_failed(row) -> bool:
    """The latest row is a finished tick that failed.

    Only the finishing attempt counts: a newer running row defers the verdict to
    its own outcome, so a retry in flight is never reported as failing.
    """
    return row["outcome"] == "failed"


def evaluate_deadman(
    state_dir: Path,
    *,
    max_age_minutes: int = 40,
    now: datetime | None = None,
) -> DeadmanVerdict:
    reference = now if now is not None else utc_now()
    limit = timedelta(minutes=max_age_minutes)
    try:
        row = _load_latest(Path(state_dir))
    except (db.StoreError, sqlite3.Error, OSError):
        return DeadmanVerdict(ok=False, reason="heartbeat_unreadable")
    if row is None:
        return DeadmanVerdict(ok=False, reason="heartbeat_unreadable")

    try:
        started_at = parse_utc_iso(row["started_at"])
        if started_at is None:
            return DeadmanVerdict(ok=False, reason="heartbeat_unreadable")
        completed_at = _derived_completed_at(started_at, row["duration_ms"])

        if _is_future(started_at, reference) or (
            completed_at is not None and _is_future(completed_at, reference)
        ):
            return DeadmanVerdict(ok=False, reason="heartbeat_future")

        if completed_at is None:
            # A running or abandoned row past the limit is a stale attempt.
            if reference - started_at > limit:
                return DeadmanVerdict(ok=False, reason="attempt_stale")
        elif reference - completed_at > limit:
            return DeadmanVerdict(ok=False, reason="completed_stale")

        if _is_failed(row):
            return DeadmanVerdict(ok=False, reason="tick_failed")

        alert_status = row["last_alert_ok"]
        if alert_status == 0:
            return DeadmanVerdict(ok=False, reason="last_alert_failed")
        if alert_status != 1:
            return DeadmanVerdict(ok=False, reason="last_alert_unknown")

        return DeadmanVerdict(ok=True, reason="ok")
    except Exception:
        return DeadmanVerdict(ok=False, reason="heartbeat_unreadable")


def _parse_max_age_min(value: str) -> int:
    try:
        minutes = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid max-age-min: {value!r}") from exc
    if not 1 <= minutes <= 1440:
        raise argparse.ArgumentTypeError(
            f"max-age-min must be between 1 and 1440, got {minutes}"
        )
    return minutes


def _parse_cli_now(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review orchestrator v1a dead-man check")
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--max-age-min", type=_parse_max_age_min, default=40)
    parser.add_argument(
        "--now",
        type=_parse_cli_now,
        default=None,
        help="Inject clock for tests (ISO-8601 UTC)",
    )
    args = parser.parse_args(argv)
    try:
        verdict = evaluate_deadman(
            args.state_dir.resolve(),
            max_age_minutes=args.max_age_min,
            now=args.now,
        )
        print(verdict.reason)
        return 0 if verdict.ok else 1
    except Exception as exc:
        print(f"deadman_error:{type(exc).__name__}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
