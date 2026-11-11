"""v1a dead-man check: read newest tick, alert if stale or last_alert_ok is false."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.review_orchestrator.persist import (
    _parse_utc_iso,
    _utc_now,
    read_newest_completed_tick_report,
)


@dataclass(frozen=True)
class DeadmanVerdict:
    ok: bool
    reason: str


def evaluate_deadman(
    state_dir: Path,
    *,
    max_age_minutes: int = 40,
    now: datetime | None = None,
) -> DeadmanVerdict:
    reference = now if now is not None else _utc_now()
    report = read_newest_completed_tick_report(state_dir, now=reference)
    if report.tick is None:
        return DeadmanVerdict(ok=False, reason="no_valid_completed_tick")

    tick = report.tick
    if tick.get("last_alert_ok", True) is False:
        return DeadmanVerdict(ok=False, reason="last_alert_ok_false")

    completed_at = _parse_utc_iso(tick.get("completed_at"))
    if completed_at is None:
        return DeadmanVerdict(ok=False, reason="no_valid_completed_tick")

    age = reference - completed_at
    if age > timedelta(minutes=max_age_minutes):
        age_min = int(age.total_seconds() // 60)
        return DeadmanVerdict(ok=False, reason=f"tick_stale_{age_min}m_gt_{max_age_minutes}m")

    return DeadmanVerdict(ok=True, reason="ok")


def _parse_cli_now(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review orchestrator v1a dead-man check")
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--max-age-min", type=int, default=40)
    parser.add_argument(
        "--now",
        type=_parse_cli_now,
        default=None,
        help="Inject clock for tests (ISO-8601 UTC)",
    )
    args = parser.parse_args(argv)
    verdict = evaluate_deadman(
        args.state_dir.resolve(),
        max_age_minutes=args.max_age_min,
        now=args.now,
    )
    print(verdict.reason)
    return 0 if verdict.ok else 1


if __name__ == "__main__":
    sys.exit(main())
