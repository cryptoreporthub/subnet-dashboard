"""Phase 1 — traffic-independent pick schedulers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import internal.council.pick_scheduler as pick_scheduler


def test_pick_scheduler_disabled(monkeypatch):
    monkeypatch.setenv("PICK_SCHEDULER_ENABLED", "off")
    pick_scheduler.stop_pick_schedulers()
    out = pick_scheduler.start_pick_schedulers()
    assert out["started"] is False
    assert out["reason"] == "disabled"


def test_daily_run_once_calls_get_or_create(monkeypatch):
    pick_scheduler.stop_pick_schedulers()
    called = {}

    def _fake_get(subnets, market_context=None, force=False):
        called["force"] = force
        called["n"] = len(subnets or [])
        return {"action": "HOLD", "date": "2026-07-26", "pick": None}

    monkeypatch.setattr(
        "internal.council.daily_pick_engine.get_or_create_today_pick",
        _fake_get,
    )
    monkeypatch.setattr(pick_scheduler, "_load_capped_subnets", lambda: [{"netuid": 1}])
    monkeypatch.setattr(pick_scheduler, "_market_context", lambda _s: {})

    sched = pick_scheduler.DailyPickScheduler()
    result = sched.run_once()
    assert result["ok"] is True
    assert called["force"] is False
    assert result["action"] == "HOLD"


def test_hour_run_once_records_prediction(monkeypatch):
    pick_scheduler.stop_pick_schedulers()
    recorded = {}

    monkeypatch.setattr(
        "internal.council.hourly_pick.select_hourly_pick",
        lambda subnets, ctx: {
            "subnet": {"netuid": 7, "name": "T"},
            "final_confidence": 0.5,
        },
    )

    def _record(pick, subnets, ctx):
        recorded["netuid"] = (pick.get("subnet") or {}).get("netuid")

    monkeypatch.setattr(pick_scheduler, "_record_hour_pick", _record)
    monkeypatch.setattr(pick_scheduler, "_load_capped_subnets", lambda: [{"netuid": 7, "price": 1.0}])
    monkeypatch.setattr(pick_scheduler, "_market_context", lambda _s: {})

    sched = pick_scheduler.HourPickScheduler(refresh_minutes=180)
    result = sched.run_once()
    assert result["ok"] is True
    assert recorded["netuid"] == 7
    assert result["netuid"] == 7


def test_start_stop_idempotent(monkeypatch):
    monkeypatch.setenv("PICK_SCHEDULER_ENABLED", "on")
    monkeypatch.setattr(pick_scheduler, "schedule_in_seconds", MagicMock())
    pick_scheduler.stop_pick_schedulers()
    first = pick_scheduler.start_pick_schedulers(immediate=False)
    second = pick_scheduler.start_pick_schedulers(immediate=False)
    assert first["started"] is True
    assert second["daily"]["started"] is False
    stop = pick_scheduler.stop_pick_schedulers()
    assert "daily" in stop


def test_boot_wires_pick_schedulers():
    boot = Path("internal/background_boot.py").read_text(encoding="utf-8")
    assert "_start_pick_schedulers" in boot
    assert "start_pick_schedulers" in boot
    assert "stop_pick_schedulers" in boot
    # Still read-only hydrate API
    server = Path("server.py").read_text(encoding="utf-8")
    # api_daily_pick must not call get_or_create on the GET path — coarse guard
    assert "def api_daily_pick" in server or "@app.get(\"/api/daily-pick\")" in server
