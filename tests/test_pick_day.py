"""Tests for pick_day module (plan §3 boundary)."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from internal.council.pick_day import daily_pick_creation_open, pick_day_str

pytestmark = pytest.mark.pick_day_boundaries


def test_pick_day_rollover_and_slot_boundaries():
    t135959 = datetime(2026, 11, 4, 13, 59, 59, tzinfo=timezone.utc)
    assert pick_day_str(t135959) == "2026-11-03"
    assert daily_pick_creation_open(t135959) is True

    t140000 = datetime(2026, 11, 4, 14, 0, 0, tzinfo=timezone.utc)
    assert pick_day_str(t140000) == "2026-11-04"
    assert daily_pick_creation_open(t140000) is False

    t140459 = datetime(2026, 11, 4, 14, 4, 59, tzinfo=timezone.utc)
    assert pick_day_str(t140459) == "2026-11-04"
    assert daily_pick_creation_open(t140459) is False

    t140500 = datetime(2026, 11, 4, 14, 5, 0, tzinfo=timezone.utc)
    assert pick_day_str(t140500) == "2026-11-04"
    assert daily_pick_creation_open(t140500) is True
