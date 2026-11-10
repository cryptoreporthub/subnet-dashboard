"""Corrupt predictions.json must not be overwritten during resolver ticks (Ditto R7)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from internal.council import resolver, resolver_scheduler
from internal.learning import predictions_store


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _long_daily_pick(netuid: int = 15, price: float = 1.23) -> list:
    return [
        {
            "date": _today(),
            "action": "long",
            "has_pick": True,
            "pick_netuid": netuid,
            "pick": {
                "action": "long",
                "final_confidence": 0.5,
                "subnet": {"netuid": netuid, "name": f"SN{netuid}", "price": price},
                "prediction": {
                    "predicted_pct": 2.5,
                    "horizon_hours": 24,
                    "reference_price": price,
                },
            },
            "market_context": {},
        }
    ]


def _hold_daily_pick() -> list:
    return [
        {
            "date": _today(),
            "action": "HOLD",
            "has_pick": False,
            "pick": None,
            "reason": "test hold",
        }
    ]


def _patch_paths(tmp_path, monkeypatch):
    preds = tmp_path / "predictions.json"
    daily = tmp_path / "daily_picks.json"
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(preds))
    monkeypatch.setattr("internal.learning.ledger_heal.PREDICTIONS_PATH", str(preds))
    monkeypatch.setattr("internal.learning.ledger_heal.DAILY_PICKS_PATH", str(daily))
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(preds))
    return preds, daily


@pytest.fixture
def _cycle_stubs(monkeypatch):
    monkeypatch.setattr(
        resolver,
        "resolve_due_predictions",
        lambda _subnets: {
            "resolved_now": [],
            "expired_now": [],
            "stats": {"pending": 0},
            "watchdog": {},
        },
    )
    monkeypatch.setattr(
        resolver,
        "expire_stale_predictions",
        lambda: {"expired_now": [], "stats": {"pending": 0}, "watchdog": {}},
    )
    monkeypatch.setattr(
        "internal.calibration.scheduler.maybe_trigger_auto_retrain",
        lambda **_kw: {"triggered": False},
    )


def test_tick_corrupt_ledger_with_published_long_leaves_file_unchanged(
    tmp_path, monkeypatch, _cycle_stubs
):
    preds, daily = _patch_paths(tmp_path, monkeypatch)
    preds.write_text("not-json{{{", encoding="utf-8")
    before = preds.read_bytes()
    daily.write_text(json.dumps(_long_daily_pick()), encoding="utf-8")

    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=15, subnet_provider=lambda: []
    )
    sched._active = True
    sched._first_tick_pending = False
    result = sched._run_refresh_cycle_with_timeout()

    assert preds.read_bytes() == before
    assert result.get("ok") is not True
    assert result.get("error") == "ledger_unreadable"


def test_tick_corrupt_ledger_hold_twice_no_predictions_write(
    tmp_path, monkeypatch, _cycle_stubs
):
    preds, daily = _patch_paths(tmp_path, monkeypatch)
    preds.write_text("{broken ledger", encoding="utf-8")
    before = preds.read_bytes()
    daily.write_text(json.dumps(_hold_daily_pick()), encoding="utf-8")

    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=15, subnet_provider=lambda: []
    )
    sched._active = True
    sched._first_tick_pending = False
    for _ in range(2):
        sched._run_refresh_cycle_with_timeout()
    assert preds.read_bytes() == before
