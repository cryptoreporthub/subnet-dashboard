"""v1a dead-man check: latest completed_at among valid ticks with seq claims."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tools.review_orchestrator.persist import (
    _parse_utc_iso,
    _tick_id_from_filename,
    _ticks_dir,
    _utc_now,
    _validate_tick_file,
)

_READ_ERRORS = (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError, RecursionError)
TICK_FILE_MAX_BYTES = 64 * 1024
CLAIM_FILE_MAX_BYTES = 64 * 1024


@dataclass(frozen=True)
class DeadmanVerdict:
    ok: bool
    reason: str


def _seq_dir(state_dir: Path) -> Path:
    return Path(state_dir) / "seq"


def _read_bounded_text(path: Path, max_bytes: int) -> str:
    size = path.stat().st_size
    if size > max_bytes:
        raise OSError("file_too_large")
    return path.read_text(encoding="utf-8")


def _read_tick_file_text(path: Path) -> str:
    return _read_bounded_text(path, TICK_FILE_MAX_BYTES)


def _load_seq_claim(state_dir: Path, seq: int) -> dict[str, Any] | None:
    path = _seq_dir(state_dir) / f"{seq}.json"
    if not path.is_file():
        return None
    try:
        raw = json.loads(_read_bounded_text(path, CLAIM_FILE_MAX_BYTES))
    except _READ_ERRORS:
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("seq") != seq:
        return None
    if _parse_utc_iso(raw.get("claimed_at")) is None:
        return None
    return raw


def _seq_claim_valid(state_dir: Path, seq: int) -> bool:
    return _load_seq_claim(state_dir, seq) is not None


def _highest_seq_claimed_at(state_dir: Path) -> datetime | None:
    seq_root = _seq_dir(state_dir)
    if not seq_root.is_dir():
        return None
    best_seq: int | None = None
    best_at: datetime | None = None
    for path in seq_root.iterdir():
        if not path.is_file() or not path.name.endswith(".json"):
            continue
        try:
            seq = int(path.stem)
        except ValueError:
            continue
        claim = _load_seq_claim(state_dir, seq)
        if claim is None:
            continue
        claimed_at = _parse_utc_iso(claim.get("claimed_at"))
        if claimed_at is None:
            continue
        if best_seq is None or seq > best_seq:
            best_seq = seq
            best_at = claimed_at
    return best_at


def _collect_valid_ticks_for_deadman(
    state_dir: Path,
    *,
    now: datetime,
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    skipped: list[str] = []
    valid: list[dict[str, Any]] = []
    ticks = _ticks_dir(state_dir)
    if not ticks.is_dir():
        return valid, tuple(skipped)

    for path in sorted(ticks.iterdir()):
        if not path.is_file():
            continue
        if _tick_id_from_filename(path.name) is None:
            skipped.append(f"{path.name}:bad_filename")
            continue
        try:
            raw = json.loads(_read_tick_file_text(path))
        except _READ_ERRORS:
            skipped.append(f"{path.name}:read_error")
            continue
        record, err = _validate_tick_file(path, raw, now=now)
        if err is not None or record is None:
            skipped.append(err or f"{path.name}:invalid")
            continue
        seq = record.get("seq")
        if not isinstance(seq, int) or not _seq_claim_valid(state_dir, seq):
            skipped.append(f"{path.name}:no_seq_claim")
            continue
        valid.append(record)

    return valid, tuple(skipped)


def _select_latest_tick_by_completed_at(ticks: list[dict[str, Any]]) -> dict[str, Any] | None:
    best_at: datetime | None = None
    for tick in ticks:
        completed_at = _parse_utc_iso(tick.get("completed_at"))
        if completed_at is None:
            continue
        if best_at is None or completed_at > best_at:
            best_at = completed_at
    if best_at is None:
        return None

    tied = [
        tick
        for tick in ticks
        if _parse_utc_iso(tick.get("completed_at")) == best_at
    ]
    for tick in tied:
        if not _last_alert_ok_passes(tick):
            return tick
    return tied[0]


def _last_alert_ok_passes(latest: dict[str, Any]) -> bool:
    return latest.get("last_alert_ok") is True


def _age_exceeds_limit(age: timedelta, limit: timedelta) -> bool:
    return age > limit


def evaluate_deadman(
    state_dir: Path,
    *,
    max_age_minutes: int = 40,
    now: datetime | None = None,
) -> DeadmanVerdict:
    reference = now if now is not None else _utc_now()
    limit = timedelta(minutes=max_age_minutes)
    last_attempt_at = _highest_seq_claimed_at(state_dir)
    if last_attempt_at is not None:
        attempt_age = reference - last_attempt_at
        if _age_exceeds_limit(attempt_age, limit):
            age_min = int(attempt_age.total_seconds() // 60)
            return DeadmanVerdict(
                ok=False,
                reason=f"last_attempt_stale_{age_min}m_gt_{max_age_minutes}m",
            )

    valid, _skipped = _collect_valid_ticks_for_deadman(state_dir, now=reference)
    latest = _select_latest_tick_by_completed_at(valid)
    if latest is None:
        return DeadmanVerdict(ok=False, reason="no_valid_completed_tick")

    if not _last_alert_ok_passes(latest):
        return DeadmanVerdict(ok=False, reason="last_alert_ok_false")

    completed_at = _parse_utc_iso(latest.get("completed_at"))
    if completed_at is None:
        return DeadmanVerdict(ok=False, reason="no_valid_completed_tick")

    age = reference - completed_at
    if _age_exceeds_limit(age, limit):
        age_min = int(age.total_seconds() // 60)
        return DeadmanVerdict(ok=False, reason=f"tick_stale_{age_min}m_gt_{max_age_minutes}m")

    return DeadmanVerdict(ok=True, reason="ok")


def _parse_max_age_min(value: str) -> int:
    try:
        minutes = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid max-age-min: {value!r}") from exc
    if minutes == 400:
        raise argparse.ArgumentTypeError(
            "max-age-min 400 is not allowed (likely typo for 40)"
        )
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
