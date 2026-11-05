"""Tests for pick_day module (plan §3 boundary)."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from internal.council.pick_day import daily_pick_creation_open, pick_day_str

pytestmark = pytest.mark.pick_day_boundaries


def test_pick_day_rollover_and_slot_boundaries():
    t185959 = datetime(2026, 11, 4, 18, 59, 59, tzinfo=timezone.utc)
    assert pick_day_str(t185959) == "2026-11-03"
    assert daily_pick_creation_open(t185959) is True

    t190000 = datetime(2026, 11, 4, 19, 0, 0, tzinfo=timezone.utc)
    assert pick_day_str(t190000) == "2026-11-04"
    assert daily_pick_creation_open(t190000) is False

    t190459 = datetime(2026, 11, 4, 19, 4, 59, tzinfo=timezone.utc)
    assert pick_day_str(t190459) == "2026-11-04"
    assert daily_pick_creation_open(t190459) is False

    t190500 = datetime(2026, 11, 4, 19, 5, 0, tzinfo=timezone.utc)
    assert pick_day_str(t190500) == "2026-11-04"
    assert daily_pick_creation_open(t190500) is True
