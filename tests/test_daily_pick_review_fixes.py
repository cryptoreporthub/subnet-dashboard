"""PR #1561 review-fix repro tests (/repro discipline)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from internal.council.daily_pick_reader import load_current_daily_pick, resolve_current_daily_pick
from internal.council.pick_day import v2_pick_id
from internal.learning.panel_summaries import summarize_picks, summarize_picks_lite


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


def test_panel_live_ignores_prior_day_reader_fallback():
    """Repro: full panel summary must not label yesterday's LONG as today's pick."""
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

    def _load():
        return [prior]

    with patch("internal.council.daily_pick_engine._load", _load):
        with patch("internal.council.daily_pick_engine.pick_day_str", return_value=day):
            with patch("internal.council.daily_pick_reader.pick_day_str", return_value=day):
                with patch("internal.subnets.feed.load_pick_subnets", return_value=[]):
                    out = summarize_picks()
    text = " ".join(out.get("sentences") or [])
    assert "Prior" not in text or "HOLD" in text


def test_loop_health_ignores_prior_day_fallback():
    """Repro: loop_health must not treat prior published row as today's pick."""
    from internal.learning.loop_health import _daily_pick_today

    prior = {
        "pick_id": v2_pick_id("2026-11-03"),
        "schema_version": 2,
        "pick_day": "2026-11-03",
        "date": "2026-11-03",
        "action": "LONG",
        "pick": {"subnet": {"netuid": 7}, "final_confidence": 0.9, "action": "long"},
    }
    import json
    import tempfile
    import os

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump([prior], handle)
        path = handle.name
    try:
        with patch("internal.council.pick_day.pick_day_str", return_value="2026-11-04"):
            with patch("internal.council.daily_pick_reader.pick_day_str", return_value="2026-11-04"):
                status = _daily_pick_today(path)
        assert status.get("has_pick") is False
    finally:
        os.unlink(path)


def test_pick_explain_prior_day_not_published_verdict(monkeypatch):
    """Repro: explain must not mark SN7 published when only prior-day pick on disk."""
    from internal.council.pick_explain import explain_subnet

    prior = {
        "pick_id": v2_pick_id("2026-11-03"),
        "schema_version": 2,
        "pick_day": "2026-11-03",
        "date": "2026-11-03",
        "action": "LONG",
        "pick": {"subnet": {"netuid": 7}, "final_confidence": 0.9, "action": "long"},
    }

    def _load():
        return [prior]

    monkeypatch.setattr("internal.council.daily_pick_engine._load", _load)
    monkeypatch.setattr("internal.council.daily_pick_engine.pick_day_str", lambda: "2026-11-04")
    monkeypatch.setattr("internal.council.daily_pick_reader.pick_day_str", lambda: "2026-11-04")
    monkeypatch.setattr(
        "internal.council.red_team.audit_daily_pick",
        lambda row, subnets: {"adjusted_confidence": 0.5, "concerns": [], "approved": True},
    )
    monkeypatch.setattr(
        "internal.council.state_vector.score_subnet_for_day",
        lambda row, ctx: {"confidence": 0.5, "total_score": 50},
    )
    out = explain_subnet(7, [{"netuid": 7, "price": 1.0}], {})
    assert out.get("verdict") != "published"
