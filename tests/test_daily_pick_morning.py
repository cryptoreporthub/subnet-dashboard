"""Daily pick morning plan integration tests (§7 subset)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from internal.council.daily_pick_engine import (
    DAILY_PICKS_PATH,
    _save,
    _upsert_today,
    get_or_create_today_pick,
)
from internal.council.daily_pick_reader import resolve_current_daily_pick
from internal.council.pick_day import pick_day_str, v2_pick_id


@pytest.fixture
def picks_path(tmp_path, monkeypatch):
    path = tmp_path / "daily_picks.json"
    monkeypatch.setattr("internal.council.daily_pick_engine.DAILY_PICKS_PATH", str(path))
    return path


def test_reader_steady_140030_shows_prior_published(picks_path):
    day = "2026-11-04"
    prior = {
        "pick_id": v2_pick_id("2026-11-03"),
        "schema_version": 2,
        "pick_day": "2026-11-03",
        "date": "2026-11-03",
        "action": "LONG",
        "pick": {"subnet": {"netuid": 1}, "final_confidence": 0.9},
    }
    picks_path.write_text(json.dumps([prior]), encoding="utf-8")
    frozen = datetime(2026, 11, 4, 14, 0, 30, tzinfo=timezone.utc)
    with patch("internal.council.daily_pick_reader.pick_day_str", return_value=day):
        row, meta = resolve_current_daily_pick(json.loads(picks_path.read_text()))
    assert row is not None
    assert row.get("pick_id") == prior["pick_id"]
    assert meta.get("prior_pick_day") is True


def test_force_true_before_slot_does_not_persist(picks_path, monkeypatch):
    frozen = datetime(2026, 11, 4, 14, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "internal.council.daily_pick_engine.daily_pick_creation_open",
        lambda now=None: False,
    )
    out = get_or_create_today_pick([{"netuid": 1, "price": 1.0}], force=True)
    assert out is None
    assert not picks_path.exists() or picks_path.read_text().strip() in ("", "[]")


def test_selection_recorded_at_utc_only_on_first_publish(picks_path, monkeypatch):
    monkeypatch.setattr(
        "internal.council.daily_pick_engine.daily_pick_creation_open",
        lambda now=None: True,
    )
    day = pick_day_str()
    hold = {
        "pick_id": v2_pick_id(day),
        "schema_version": 2,
        "pick_day": day,
        "date": day,
        "action": "HOLD",
        "pick": None,
        "build_started_at": "2026-01-01T00:00:00Z",
    }
    published = dict(hold)
    published["action"] = "LONG"
    published["pick"] = {"subnet": {"netuid": 2}, "final_confidence": 0.99, "action": "long"}
    published["selection_recorded_at_utc"] = "2026-01-02T00:00:00Z"
    merged = _upsert_today([hold], published)
    assert _save(merged)
    disk = json.loads(picks_path.read_text())
    row = disk[-1]
    assert row["selection_recorded_at_utc"] == "2026-01-02T00:00:00Z"
