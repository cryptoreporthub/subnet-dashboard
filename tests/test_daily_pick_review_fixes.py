"""PR #1561 review-fix repro tests (/repro discipline)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from internal.council.daily_pick_reader import load_current_daily_pick, resolve_current_daily_pick
from internal.council.pick_day import v2_pick_id
from internal.learning.panel_summaries import summarize_picks_lite


def test_malformed_null_row_does_not_break_reader():
    """Repro: Ditto chat/letter — null in daily_picks list must not raise."""
    prior = {
        "pick_id": v2_pick_id("2026-11-03"),
        "schema_version": 2,
        "pick_day": "2026-11-03",
        "date": "2026-11-03",
        "action": "LONG",
        "pick": {"subnet": {"netuid": 7}, "final_confidence": 0.9, "action": "long"},
    }
    records = [None, prior]
    row, meta = resolve_current_daily_pick(records, now_pick_day="2026-11-04")
    assert row is not None
    assert meta.get("prior_pick_day") is True


def test_panel_lite_ignores_prior_day_reader_fallback():
    """Repro: lite summary must not label yesterday's LONG as today's pick."""
    day = "2026-11-04"
    prior = {
        "pick_id": v2_pick_id("2026-11-03"),
        "schema_version": 2,
        "pick_day": "2026-11-03",
        "date": "2026-11-03",
        "action": "LONG",
        "pick": {
            "subnet": {"netuid": 7, "name": "Prior"},
            "final_confidence": 0.9,
            "action": "long",
            "audit": {"approved": True, "concerns": []},
        },
    }
    frozen = datetime(2026, 11, 4, 19, 2, 0, tzinfo=timezone.utc)

    def _load():
        return [prior]

    with patch("internal.council.daily_pick_engine._load", _load):
        with patch("internal.council.daily_pick_engine.pick_day_str", return_value=day):
            with patch("internal.council.daily_pick_reader.pick_day_str", return_value=day):
                out = summarize_picks_lite()
    text = " ".join(out.get("sentences") or [])
    assert "Prior" not in text or "unavailable" in text.lower() or "HOLD" in text
