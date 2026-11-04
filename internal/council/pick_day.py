"""Pick-day calendar + daily-pick creation slot (morning plan §3–§4)."""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

PICK_DAY_ROLLOVER_UTC_HOUR = int(os.environ.get("PICK_DAY_ROLLOVER_UTC_HOUR", "13"))
PICK_DAY_ROLLOVER_UTC_MINUTE = int(os.environ.get("PICK_DAY_ROLLOVER_UTC_MINUTE", "0"))

DAILY_PICK_SLOT_UTC_HOUR = int(os.environ.get("DAILY_PICK_SLOT_UTC_HOUR", "13"))
DAILY_PICK_SLOT_UTC_MINUTE = int(os.environ.get("DAILY_PICK_SLOT_UTC_MINUTE", "5"))


def pick_day_str(now: Optional[datetime] = None) -> str:
    """ISO pick-day string with 13:00 UTC rollover (env-overridable)."""
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rollover = time(PICK_DAY_ROLLOVER_UTC_HOUR, PICK_DAY_ROLLOVER_UTC_MINUTE)
    if now_utc.time() < rollover:
        return (now_utc.date() - timedelta(days=1)).isoformat()
    return now_utc.date().isoformat()


def pick_day_start_utc(pick_day: str) -> datetime:
    d = date.fromisoformat(pick_day)
    return datetime.combine(
        d,
        time(PICK_DAY_ROLLOVER_UTC_HOUR, PICK_DAY_ROLLOVER_UTC_MINUTE),
        tzinfo=timezone.utc,
    )


def slot_open_utc(pick_day: str) -> datetime:
    d = date.fromisoformat(pick_day)
    return datetime.combine(
        d,
        time(DAILY_PICK_SLOT_UTC_HOUR, DAILY_PICK_SLOT_UTC_MINUTE),
        tzinfo=timezone.utc,
    )


def daily_pick_creation_open(now: Optional[datetime] = None) -> bool:
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    pick_day = pick_day_str(now_utc)
    return now_utc >= slot_open_utc(pick_day)


def v2_pick_id(pick_day: str) -> str:
    return f"v2:{pick_day}"
