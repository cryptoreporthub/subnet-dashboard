"""Regression tests for resolver missing-price retry semantics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from internal.council.resolver_semantics_patch import apply_resolver_semantics_patch


@pytest.fixture
def resolver(monkeypatch):
    apply_resolver_semantics_patch()
    import internal.council.resolver as resolver_mod

    monkeypatch.setattr(resolver_mod, "_load_json", lambda *args, **kwargs: {}, raising=False)
    for name in (
        "on_prediction_resolved",
        "_nudge_weights",
        "_record_scenario_outcome",
        "_nudge_signal_weights",
    ):
        monkeypatch.setattr(resolver_mod, name, lambda *args, **kwargs: None, raising=False)
    return resolver_mod


def _prediction(resolve_at: datetime, **overrides):
    payload = {
        "id": "pred-1",
        "netuid": 42,
        "resolve_at": resolve_at.isoformat().replace("+00:00", "Z"),
        "horizon_hours": 1,
        "reference_price": 100.0,
        "direction": "up",
        "predicted_pct": 5.0,
    }
    payload.update(overrides)
    return payload


def test_missing_price_stays_pending_and_expires_after_cap(resolver, monkeypatch):
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    resolve_at = now - timedelta(hours=6)
    monkeypatch.setattr(
        resolver,
        "price_at_resolve_at",
        lambda *args, **kwargs: ("ungradeable", 0.0, {"candles_in_window": 0, "price_source": None}),
        raising=False,
    )

    pred = _prediction(resolve_at)
    for attempt in range(1, 4):
        pred = resolver.resolve_prediction_at_horizon(pred, now=now + timedelta(minutes=attempt), live_prices={})
        assert pred["status"] == "pending"
        assert pred["resolve_attempts"] == attempt
        assert pred["price_data_unavailable"] is True

    expired = resolver.resolve_prediction_at_horizon(pred, now=now + timedelta(hours=5), live_prices={})
    assert expired["status"] == "expired"
    assert expired["expired_reason"] == "price_data_unavailable"
    assert expired["retirement_reason"] == "missing_price_at_horizon"
    assert expired["resolve_attempts"] == 3


def test_real_snapshot_miss_grades_normally(resolver, monkeypatch):
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    resolve_at = now - timedelta(hours=6)
    monkeypatch.setattr(
        resolver,
        "price_at_resolve_at",
        lambda *args, **kwargs: ("ok", 105.0, {"candles_in_window": 5, "price_source": "vwap"}),
        raising=False,
    )

    pred = _prediction(resolve_at, direction="down", predicted_pct=-5.0)
    result = resolver.resolve_prediction_at_horizon(pred, now=now, live_prices={})

    assert result["status"] == "resolved"
    assert result["outcome"] == "miss"
    assert result["correct"] is False
    assert result["resolved_price"] == 105.0
    assert "resolve_attempts" not in result or result["resolve_attempts"] in (0, None)


def test_expiry_grace_is_four_horizon_hours(resolver):
    assert resolver._EXPIRY_GRACE_MULTIPLE == 4.0

    resolve_at = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    pred = {"horizon_hours": 1}

    assert resolver._is_expired(pred, resolve_at, resolve_at + timedelta(hours=3), 2.0) is False
    assert resolver._is_expired(pred, resolve_at, resolve_at + timedelta(hours=5), 2.0) is True


def test_stats_expose_council_and_pump_pending_separately(resolver):
    stats = resolver._compute_stats(
        {
            "resolved": [],
            "predictions": [
                {"id": "council", "status": "pending"},
                {"id": "pump", "status": "pending", "pick_source": "pump_lead"},
            ],
        }
    )
    assert stats["pending"] == 1
    assert stats["council_pending"] == 1
    assert stats["pump_pending"] == 1
    assert stats["total_pending"] == 2
