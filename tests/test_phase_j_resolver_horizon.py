"""Phase J — horizon-end resolve, expire-late, watchdog."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

import internal.council.resolver as resolver
from internal.council.price_reference import CANDLE_LOOKUP_MINUTES


def _write_price_cache(path: str, netuid: int, resolve_at: datetime, price: float) -> None:
    candles = []
    for offset_min in (-10, 0, 10):
        ts = (resolve_at + timedelta(minutes=offset_min)).isoformat().replace("+00:00", "Z")
        candles.append(
            {
                "timestamp": ts,
                "close": price + offset_min * 0.01,
                "volume": 1000.0,
            }
        )
    cache = {str(netuid): {"candles": candles}}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cache, fh)


@pytest.fixture(autouse=True)
def isolate_paths(tmp_path, monkeypatch):
    pred_path = str(tmp_path / "predictions.json")
    cache_path = str(tmp_path / "price_cache.json")
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", pred_path)
    monkeypatch.setattr(resolver, "PRICE_CACHE_PATH", cache_path)


def test_late_resolve_expires_instead_of_wrong_price():
    resolve_at = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    grace_end = resolve_at + timedelta(hours=2)  # 1h horizon × 2
    now = grace_end + timedelta(minutes=1)
    pred = {
        "id": "late-1",
        "netuid": 7,
        "reference_price": 100.0,
        "predicted_pct": 5.0,
        "direction": "up",
        "horizon_hours": 1,
        "resolve_at": resolve_at.isoformat().replace("+00:00", "Z"),
        "created_at": (resolve_at - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }
    _write_price_cache(resolver.PRICE_CACHE_PATH, 7, resolve_at, 150.0)

    result = resolver.resolve_prediction_at_horizon(pred, now=now, live_prices={7: 150.0})

    assert result["status"] == "expired"
    assert result["outcome"] == "expired"
    assert result.get("resolved_price") is None


def test_resolve_uses_horizon_candle_not_late_live_price():
    resolve_at = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    now = resolve_at + timedelta(minutes=5)
    pred = {
        "id": "horizon-1",
        "netuid": 3,
        "reference_price": 100.0,
        "predicted_pct": 5.0,
        "direction": "up",
        "horizon_hours": 1,
        "resolve_at": resolve_at.isoformat().replace("+00:00", "Z"),
    }
    _write_price_cache(resolver.PRICE_CACHE_PATH, 3, resolve_at, 110.0)

    result = resolver.resolve_prediction_at_horizon(
        pred,
        now=now,
        live_prices={3: 200.0},
    )

    assert result["status"] == "resolved"
    assert result["correct"] is True
    assert result["resolved_price"] == pytest.approx(110.0, rel=1e-3)
    assert result.get("price_source") in {"vwap", "median"}


def test_watchdog_flags_large_backlog():
    from internal.council.watchdog import check_resolver_watchdog

    pending = [{"id": f"p{i}", "created_at": "2026-07-01T00:00:00Z", "horizon_hours": 1} for i in range(11)]
    now = datetime(2026, 7, 1, 1, 0, tzinfo=timezone.utc)
    status = check_resolver_watchdog(pending, now=now)
    assert status["warning"] is True
    assert status["reason"] == "pending_count_exceeded"


def test_ungradeable_stays_pending_until_grace():
    resolve_at = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    now = resolve_at + timedelta(minutes=30)
    pred = {
        "id": "nograde-1",
        "netuid": 99,
        "reference_price": 100.0,
        "predicted_pct": 5.0,
        "direction": "up",
        "horizon_hours": 1,
        "resolve_at": resolve_at.isoformat().replace("+00:00", "Z"),
    }
    with open(resolver.PRICE_CACHE_PATH, "w", encoding="utf-8") as fh:
        json.dump({}, fh)

    result = resolver.resolve_prediction_at_horizon(pred, now=now, live_prices={})
    assert result["status"] == "pending"

    expired_now = resolve_at + timedelta(hours=2, minutes=1)
    result2 = resolver.resolve_prediction_at_horizon(pred, now=expired_now, live_prices={})
    assert result2["status"] == "expired"
