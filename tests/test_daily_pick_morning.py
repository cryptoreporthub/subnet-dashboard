"""Daily pick morning plan integration tests (§7 subset)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from internal.council.daily_pick_engine import (
    DAILY_PICKS_PATH,
    DailyPickFileCorrupt,
    _load,
    _save,
    _upsert_today,
    get_or_create_today_pick,
)
from internal.council.daily_pick_reader import (
    is_published_daily_pick_row,
    legacy_row_counts_for_pick_day,
    legacy_row_write_instant,
    load_current_daily_pick,
    resolve_current_daily_pick,
)
from internal.council.pick_day import daily_pick_creation_open, pick_day_str, v2_pick_id


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
    frozen = datetime(2026, 11, 4, 19, 0, 30, tzinfo=timezone.utc)
    with patch("internal.council.daily_pick_reader.pick_day_str", return_value=day):
        row, meta = resolve_current_daily_pick(json.loads(picks_path.read_text()))
    assert row is not None
    assert row.get("pick_id") == prior["pick_id"]
    assert meta.get("prior_pick_day") is True


def test_force_true_before_slot_does_not_persist(picks_path, monkeypatch):
    frozen = datetime(2026, 11, 4, 19, 0, 0, tzinfo=timezone.utc)
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
    from internal.council.daily_pick_write_token import current_write_generation

    assert _save(merged, write_generation=current_write_generation())
    disk = json.loads(picks_path.read_text())
    row = disk[-1]
    assert row["selection_recorded_at_utc"] == "2026-01-02T00:00:00Z"


def _bind_pick_clock(monkeypatch, instant: datetime) -> None:
    import internal.council.pick_day as pick_day_mod

    real_pick_day_str = pick_day_mod.pick_day_str

    def _str(now=None):
        return real_pick_day_str(now or instant)

    def _open(now=None):
        now_utc = (now or instant).astimezone(timezone.utc)
        day = _str(now_utc)
        return now_utc >= pick_day_mod.slot_open_utc(day)

    monkeypatch.setattr(pick_day_mod, "pick_day_str", _str)
    monkeypatch.setattr(pick_day_mod, "daily_pick_creation_open", _open)
    for target in (
        "internal.council.daily_pick_reader.pick_day_str",
        "internal.council.daily_pick_engine.pick_day_str",
    ):
        monkeypatch.setattr(target, _str)


@pytest.mark.pick_day_boundaries
def test_prod_legacy_0015_row_v2_at_slot_no_hold_served(picks_path, monkeypatch):
    """Deploy-shaped legacy row at 00:15 UTC must not block v2 at 14:05 or serve HOLD."""
    prior = {
        "pick_id": v2_pick_id("2026-11-03"),
        "schema_version": 2,
        "pick_day": "2026-11-03",
        "date": "2026-11-03",
        "action": "LONG",
        "pick": {"subnet": {"netuid": 7}, "final_confidence": 0.88, "action": "long"},
    }
    legacy_today = {
        "date": "2026-11-04",
        "action": "LONG",
        "pick": {"subnet": {"netuid": 99}, "final_confidence": 0.91, "action": "long"},
        "timestamp_utc": "2026-11-04T00:15:00Z",
        "build_started_at": "2026-11-04T00:15:00Z",
    }
    picks_path.write_text(json.dumps([prior, legacy_today]), encoding="utf-8")

    t1340 = datetime(2026, 11, 4, 18, 40, 0, tzinfo=timezone.utc)
    _bind_pick_clock(monkeypatch, t1340)
    records = json.loads(picks_path.read_text())
    row, meta = load_current_daily_pick(records)
    assert row is not None
    assert is_published_daily_pick_row(row)
    assert row.get("pick_id") == prior["pick_id"]
    assert meta.get("prior_pick_day") is False
    assert pick_day_str(t1340) == "2026-11-03"
    assert row.get("pick", {}).get("subnet", {}).get("netuid") == 7

    t1442 = datetime(2026, 11, 4, 19, 42, 0, tzinfo=timezone.utc)
    _bind_pick_clock(monkeypatch, t1442)
    records = json.loads(picks_path.read_text())
    row, meta = load_current_daily_pick(records)
    assert row is not None
    assert is_published_daily_pick_row(row)
    assert row.get("date") == "2026-11-04"
    assert row.get("pick_id") is None
    assert meta.get("prior_pick_day") is False
    assert row.get("pick", {}).get("subnet", {}).get("netuid") == 99
    assert legacy_row_write_instant(legacy_today) is not None
    assert not legacy_row_counts_for_pick_day(legacy_today, pick_day_str(t1442))

    monkeypatch.setattr(
        "internal.council.daily_pick_engine.select_daily_pick",
        lambda subnets, ctx: {
            "subnet": {"netuid": 12, "name": "SlotPick"},
            "final_confidence": 0.55,
            "action": "long",
        },
    )
    monkeypatch.setattr(
        "internal.council.daily_pick_engine.directional_publish_guard",
        lambda _p: {"approved": True, "reason": ""},
    )
    monkeypatch.setattr("internal.council.daily_pick_engine.publish_gate_fraction", lambda: 0.0)
    monkeypatch.setattr(
        "internal.learning.prediction_loop.record_pick_prediction",
        lambda *_a, **_k: None,
    )

    t1405 = datetime(2026, 11, 4, 19, 5, 0, tzinfo=timezone.utc)
    _bind_pick_clock(monkeypatch, t1405)
    assert daily_pick_creation_open(t1405) is True
    out = get_or_create_today_pick([{"netuid": 12, "price": 1.0}], force=False)
    assert out is not None
    assert out.get("pick_id") == v2_pick_id("2026-11-04")
    assert int(out.get("schema_version") or 0) >= 2
    assert str(out.get("action", "")).upper() in ("LONG", "BUY")

    disk = json.loads(picks_path.read_text())
    v2_rows = [r for r in disk if r.get("pick_id") == v2_pick_id("2026-11-04")]
    assert len(v2_rows) == 1
    legacy_rows = [r for r in disk if r.get("date") == "2026-11-04" and not r.get("pick_id")]
    assert len(legacy_rows) == 1
    assert disk[0].get("pick_id") == prior["pick_id"]
    hero, hero_meta = load_current_daily_pick(disk)
    assert hero is not None
    assert is_published_daily_pick_row(hero)
    assert hero_meta.get("prior_pick_day") is False
    assert hero.get("pick_id") == v2_pick_id("2026-11-04")


@pytest.mark.pick_day_boundaries
def test_legacy_restamp_after_rollover_does_not_block_v2(picks_path, monkeypatch):
    """P1-a: restamped build_started_at must not make legacy count as today's v2 row."""
    from internal.council.daily_pick_engine import _find_today

    prior = {
        "pick_id": v2_pick_id("2026-11-03"),
        "schema_version": 2,
        "pick_day": "2026-11-03",
        "date": "2026-11-03",
        "action": "LONG",
        "pick": {"subnet": {"netuid": 7}, "final_confidence": 0.88, "action": "long"},
    }
    legacy_restamp = {
        "date": "2026-11-04",
        "action": "LONG",
        "pick": {"subnet": {"netuid": 99}, "final_confidence": 0.91, "action": "long"},
        "timestamp_utc": "2026-11-04T00:15:00Z",
        "build_started_at": "2026-11-04T15:00:00Z",
    }
    picks_path.write_text(json.dumps([prior, legacy_restamp]), encoding="utf-8")
    t1405 = datetime(2026, 11, 4, 19, 5, 0, tzinfo=timezone.utc)
    _bind_pick_clock(monkeypatch, t1405)
    assert not legacy_row_counts_for_pick_day(legacy_restamp, "2026-11-04")
    assert _find_today(json.loads(picks_path.read_text())) is None

    monkeypatch.setattr(
        "internal.council.daily_pick_engine.select_daily_pick",
        lambda subnets, ctx: {
            "subnet": {"netuid": 12, "name": "SlotPick"},
            "final_confidence": 0.55,
            "action": "long",
        },
    )
    monkeypatch.setattr(
        "internal.council.daily_pick_engine.directional_publish_guard",
        lambda _p: {"approved": True, "reason": ""},
    )
    monkeypatch.setattr("internal.council.daily_pick_engine.publish_gate_fraction", lambda: 0.0)
    monkeypatch.setattr(
        "internal.learning.prediction_loop.record_pick_prediction",
        lambda *_a, **_k: None,
    )
    out = get_or_create_today_pick([{"netuid": 12, "price": 1.0}], force=False)
    assert out is not None
    assert out.get("pick_id") == v2_pick_id("2026-11-04")


@pytest.mark.pick_day_boundaries
def test_deploy_after_slot_catch_up_tick_publishes_v2(picks_path, monkeypatch):
    """Worker starts 15:00 UTC after slot; first catch-up tick publishes v2, no HOLD served."""
    from internal.council import pick_scheduler
    from internal.council.daily_pick_write_token import issue_daily_pick_write_token

    prior = {
        "pick_id": v2_pick_id("2026-11-03"),
        "schema_version": 2,
        "pick_day": "2026-11-03",
        "date": "2026-11-03",
        "action": "LONG",
        "pick": {"subnet": {"netuid": 7}, "final_confidence": 0.88, "action": "long"},
    }
    legacy_today = {
        "date": "2026-11-04",
        "action": "LONG",
        "pick": {"subnet": {"netuid": 99}, "final_confidence": 0.91, "action": "long"},
        "timestamp_utc": "2026-11-04T00:15:00Z",
        "build_started_at": "2026-11-04T00:15:00Z",
    }
    picks_path.write_text(json.dumps([prior, legacy_today]), encoding="utf-8")

    t1500 = datetime(2026, 11, 4, 20, 0, 0, tzinfo=timezone.utc)
    _bind_pick_clock(monkeypatch, t1500)

    def _assert_no_hold_served(records):
        row, _meta = load_current_daily_pick(records)
        assert row is not None
        assert str(row.get("action", "")).upper() != "HOLD"
        assert is_published_daily_pick_row(row)

    _assert_no_hold_served(json.loads(picks_path.read_text()))
    assert daily_pick_creation_open(t1500) is True
    assert not legacy_row_counts_for_pick_day(legacy_today, pick_day_str(t1500))

    issue_daily_pick_write_token()
    monkeypatch.setattr(
        "internal.council.daily_pick_write_token.fence_revoke_if_resolver_wait_exceeded",
        lambda **_k: True,
    )
    monkeypatch.setattr(
        "internal.council.daily_pick_engine.select_daily_pick",
        lambda subnets, ctx: {
            "subnet": {"netuid": 12, "name": "CatchUpPick"},
            "final_confidence": 0.55,
            "action": "long",
        },
    )
    monkeypatch.setattr(
        "internal.council.daily_pick_engine.directional_publish_guard",
        lambda _p: {"approved": True, "reason": ""},
    )
    monkeypatch.setattr("internal.council.daily_pick_engine.publish_gate_fraction", lambda: 0.0)
    monkeypatch.setattr(
        "internal.learning.prediction_loop.record_pick_prediction",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(pick_scheduler, "_load_subnets", lambda: [{"netuid": 12, "price": 1.0}])
    monkeypatch.setattr(pick_scheduler, "_market_context", lambda _s: {})
    pick_scheduler.stop_pick_schedulers()

    sched = pick_scheduler.DailyPickScheduler()
    result = sched.run_once()

    assert result.get("ok") is True
    assert str(result.get("action", "")).upper() in ("LONG", "BUY")

    disk = json.loads(picks_path.read_text())
    v2_rows = [r for r in disk if r.get("pick_id") == v2_pick_id("2026-11-04")]
    assert len(v2_rows) == 1
    assert int(v2_rows[0].get("schema_version") or 0) >= 2
    _assert_no_hold_served(disk)
    hero, hero_meta = load_current_daily_pick(disk)
    assert hero.get("pick_id") == v2_pick_id("2026-11-04")
    assert hero_meta.get("prior_pick_day") is False


@pytest.mark.pick_day_boundaries
def test_legacy_rows_preserved_when_v2_written(picks_path, monkeypatch):
    """Prod legacy + prior v2 day must remain on disk after v2 upsert."""
    day = "2026-11-04"
    prior = {
        "pick_id": v2_pick_id("2026-11-03"),
        "schema_version": 2,
        "pick_day": "2026-11-03",
        "date": "2026-11-03",
        "action": "LONG",
        "pick": {"subnet": {"netuid": 7}, "final_confidence": 0.88, "action": "long"},
    }
    legacy_today = {
        "date": day,
        "action": "LONG",
        "pick": {"subnet": {"netuid": 99}, "final_confidence": 0.91, "action": "long"},
        "timestamp_utc": "2026-11-04T00:15:00Z",
        "build_started_at": "2026-11-04T00:15:00Z",
    }
    picks_path.write_text(json.dumps([prior, legacy_today]), encoding="utf-8")
    t1405 = datetime(2026, 11, 4, 19, 5, 0, tzinfo=timezone.utc)
    _bind_pick_clock(monkeypatch, t1405)
    monkeypatch.setattr(
        "internal.council.daily_pick_engine.daily_pick_creation_open",
        lambda now=None: True,
    )
    v2_long = {
        "pick_id": v2_pick_id(day),
        "schema_version": 2,
        "pick_day": day,
        "date": day,
        "action": "LONG",
        "pick": {"subnet": {"netuid": 12}, "final_confidence": 0.6, "action": "long"},
        "build_started_at": "2026-11-04T19:05:00Z",
    }
    merged = _upsert_today(json.loads(picks_path.read_text()), v2_long)
    from internal.council.daily_pick_write_token import current_write_generation

    assert _save(merged, write_generation=current_write_generation())
    disk = json.loads(picks_path.read_text())
    assert len(disk) == 3
    assert any(r.get("pick_id") == v2_pick_id(day) for r in disk)
    assert any(r.get("pick_id") == prior["pick_id"] for r in disk)
    assert any(r.get("date") == day and not r.get("pick_id") for r in disk)


@pytest.mark.pick_day_boundaries
def test_v2_hold_on_disk_not_served_by_reader(picks_path):
    day = "2026-11-04"
    legacy_today = {
        "date": day,
        "action": "LONG",
        "pick": {"subnet": {"netuid": 99}, "final_confidence": 0.91, "action": "long"},
        "timestamp_utc": "2026-11-04T00:15:00Z",
    }
    hold = {
        "pick_id": v2_pick_id(day),
        "schema_version": 2,
        "pick_day": day,
        "date": day,
        "action": "HOLD",
        "pick": None,
        "build_started_at": "2026-11-04T19:05:00Z",
    }
    records = [legacy_today, hold]
    with patch("internal.council.daily_pick_reader.pick_day_str", return_value=day):
        row, meta = load_current_daily_pick(records)
    assert row is None
    assert meta.get("prior_pick_day") is False


@pytest.mark.pick_day_boundaries
def test_scheduler_cold_start_1445_utc_first_tick_publishes_v2(picks_path, monkeypatch):
    """Real pick_day clock at 14:45 UTC — no conftest freeze; v2 on first tick."""
    from internal.council import pick_scheduler
    from internal.council.daily_pick_write_token import issue_daily_pick_write_token
    import internal.council.pick_day as pick_day_mod

    prior = {
        "pick_id": v2_pick_id("2026-11-03"),
        "schema_version": 2,
        "pick_day": "2026-11-03",
        "date": "2026-11-03",
        "action": "LONG",
        "pick": {"subnet": {"netuid": 7}, "final_confidence": 0.88, "action": "long"},
    }
    legacy_today = {
        "date": "2026-11-04",
        "action": "LONG",
        "pick": {"subnet": {"netuid": 99}, "final_confidence": 0.91, "action": "long"},
        "timestamp_utc": "2026-11-04T00:15:00Z",
    }
    picks_path.write_text(json.dumps([prior, legacy_today]), encoding="utf-8")

    t1445 = datetime(2026, 11, 4, 19, 45, 0, tzinfo=timezone.utc)
    _bind_pick_clock(monkeypatch, t1445)
    assert pick_day_mod.pick_day_str(t1445) == "2026-11-04"
    assert pick_day_mod.daily_pick_creation_open(t1445) is True

    row, _meta = load_current_daily_pick(json.loads(picks_path.read_text()))
    assert row.get("pick", {}).get("subnet", {}).get("netuid") == 99

    issue_daily_pick_write_token()
    monkeypatch.setattr(
        "internal.council.daily_pick_write_token.fence_revoke_if_resolver_wait_exceeded",
        lambda **_k: True,
    )
    monkeypatch.setattr(
        "internal.council.daily_pick_engine.select_daily_pick",
        lambda subnets, ctx: {
            "subnet": {"netuid": 12, "name": "ColdStart"},
            "final_confidence": 0.55,
            "action": "long",
        },
    )
    monkeypatch.setattr(
        "internal.council.daily_pick_engine.directional_publish_guard",
        lambda _p: {"approved": True, "reason": ""},
    )
    monkeypatch.setattr("internal.council.daily_pick_engine.publish_gate_fraction", lambda: 0.0)
    monkeypatch.setattr(
        "internal.learning.prediction_loop.record_pick_prediction",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(pick_scheduler, "_load_subnets", lambda: [{"netuid": 12, "price": 1.0}])
    monkeypatch.setattr(pick_scheduler, "_market_context", lambda _s: {})
    monkeypatch.setattr(
        "internal.council.daily_pick_engine._now_stamp",
        lambda: "2026-11-04T19:45:01Z",
    )
    pick_scheduler.stop_pick_schedulers()
    result = pick_scheduler.DailyPickScheduler().run_once()
    assert result.get("ok") is True
    disk = json.loads(picks_path.read_text())
    assert len([r for r in disk if r.get("pick_id") == v2_pick_id("2026-11-04")]) == 1
    hero, _ = load_current_daily_pick(disk)
    assert hero.get("pick_id") == v2_pick_id("2026-11-04")


@pytest.mark.pick_day_boundaries
def test_prior_day_tiebreak_v2_wins_over_legacy_on_2026_11_05_gap():
    """19:02 UTC 2026-11-05 (post-rollover, pre-slot): v2:2026-11-04 beats legacy same date."""
    day = "2026-11-05"
    legacy = {
        "date": "2026-11-04",
        "action": "LONG",
        "pick": {"subnet": {"netuid": 99}, "final_confidence": 0.91, "action": "long"},
        "timestamp_utc": "2026-11-04T00:15:00Z",
    }
    v2_row = {
        "pick_id": v2_pick_id("2026-11-04"),
        "schema_version": 2,
        "pick_day": "2026-11-04",
        "date": "2026-11-04",
        "action": "LONG",
        "pick": {"subnet": {"netuid": 12}, "final_confidence": 0.6, "action": "long"},
        "build_started_at": "2026-11-04T19:05:00Z",
    }
    records = [legacy, v2_row]
    with patch("internal.council.daily_pick_reader.pick_day_str", return_value=day):
        row, meta = load_current_daily_pick(records)
    assert row is not None
    assert row.get("pick_id") == v2_pick_id("2026-11-04")
    assert meta.get("prior_pick_day") is True


def test_corrupt_daily_picks_json_raises_not_empty(picks_path):
    picks_path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(DailyPickFileCorrupt):
        _load(str(picks_path))


def test_corrupt_daily_picks_non_list_raises(picks_path):
    picks_path.write_text(json.dumps({"oops": 1}), encoding="utf-8")
    with pytest.raises(DailyPickFileCorrupt):
        _load(str(picks_path))
