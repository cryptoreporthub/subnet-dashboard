"""v1a dead-man check: read trusted heartbeat/latest.json only."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tools.review_orchestrator.persist import _parse_utc_iso, _utc_now

_READ_ERRORS = (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError, RecursionError)
HEARTBEAT_FILE_MAX_BYTES = 4 * 1024
_FUTURE_SLACK = timedelta(minutes=5)


@dataclass(frozen=True)
class DeadmanVerdict:
    ok: bool
    reason: str


def _heartbeat_path(state_dir: Path) -> Path:
    return Path(state_dir) / "heartbeat" / "latest.json"


def _read_heartbeat_text(path: Path) -> str:
    size = path.stat().st_size
    if size > HEARTBEAT_FILE_MAX_BYTES:
        raise OSError("file_too_large")
    return path.read_text(encoding="utf-8")


def _parse_heartbeat_record(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    tick_id = raw.get("tick_id")
    attempt_at = raw.get("attempt_at")
    completed_at = raw.get("completed_at")
    if not isinstance(tick_id, str) or not tick_id:
        return None
    if not isinstance(attempt_at, str) or not isinstance(completed_at, str):
        return None
    if "last_alert_ok" in raw and not isinstance(raw["last_alert_ok"], bool):
        return None
    if _parse_utc_iso(attempt_at) is None or _parse_utc_iso(completed_at) is None:
        return None
    return raw


def _load_heartbeat(state_dir: Path) -> dict[str, Any] | None:
    path = _heartbeat_path(state_dir)
    if not path.is_file():
        return None
    try:
        text = _read_heartbeat_text(path)
        raw = json.loads(text)
    except _READ_ERRORS:
        return None
    return _parse_heartbeat_record(raw)


def _is_stale(age: timedelta, limit: timedelta) -> bool:
    return age > limit


def _is_future(ts: datetime, reference: datetime) -> bool:
    return ts > reference + _FUTURE_SLACK


def evaluate_deadman(
    state_dir: Path,
    *,
    max_age_minutes: int = 40,
    now: datetime | None = None,
) -> DeadmanVerdict:
    reference = now if now is not None else _utc_now()
    limit = timedelta(minutes=max_age_minutes)
    record = _load_heartbeat(state_dir)
    if record is None:
        return DeadmanVerdict(ok=False, reason="heartbeat_unreadable")

    attempt_at = _parse_utc_iso(record["attempt_at"])
    completed_at = _parse_utc_iso(record["completed_at"])
    assert attempt_at is not None and completed_at is not None

    if _is_future(attempt_at, reference) or _is_future(completed_at, reference):
        return DeadmanVerdict(ok=False, reason="heartbeat_future")

    attempt_age = reference - attempt_at
    if _is_stale(attempt_age, limit):
        return DeadmanVerdict(ok=False, reason="attempt_stale")

    completed_age = reference - completed_at
    if _is_stale(completed_age, limit):
        return DeadmanVerdict(ok=False, reason="completed_stale")

    if record.get("last_alert_ok") is False:
        return DeadmanVerdict(ok=False, reason="last_alert_failed")

    return DeadmanVerdict(ok=True, reason="ok")


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
