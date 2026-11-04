"""Tests for pick_day module (plan §3 boundary)."""

from __future__ import annotations

from datetime import datetime, timezone

from internal.council.pick_day import daily_pick_creation_open, pick_day_str


def test_pick_day_rollover_and_slot_boundaries():
    t125959 = datetime(2026, 11, 4, 12, 59, 59, tzinfo=timezone.utc)
    assert pick_day_str(t125959) == "2026-11-03"
    assert daily_pick_creation_open(t125959) is True

    t130000 = datetime(2026, 11, 4, 13, 0, 0, tzinfo=timezone.utc)
    assert pick_day_str(t130000) == "2026-11-04"
    assert daily_pick_creation_open(t130000) is False

    t130459 = datetime(2026, 11, 4, 13, 4, 59, tzinfo=timezone.utc)
    assert pick_day_str(t130459) == "2026-11-04"
    assert daily_pick_creation_open(t130459) is False

    t130500 = datetime(2026, 11, 4, 13, 5, 0, tzinfo=timezone.utc)
    assert pick_day_str(t130500) == "2026-11-04"
    assert daily_pick_creation_open(t130500) is True
