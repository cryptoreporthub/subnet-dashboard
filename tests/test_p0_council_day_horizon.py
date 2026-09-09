"""P0.5 — Council day predictions locked to canonical 24h horizon."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from internal.council.resolver import resolve_prediction_at_horizon
from internal.council.state_vector import attach_council_prediction
from internal.learning.pick_horizon import COUNCIL_DAY_HORIZON_HOURS, day_horizon_hours
from internal.learning.prediction_loop import record_pick_prediction


def test_council_day_horizon_constant_is_24():
    assert COUNCIL_DAY_HORIZON_HOURS == 24
    assert day_horizon_hours() == 24.0 or day_horizon_hours() == 24


def test_attach_council_day_defaults_to_24h_even_if_env_says_4(monkeypatch):
    monkeypatch.setenv("ACC2_DAY_HORIZON_HOURS", "4")
    monkeypatch.setenv("DAY_PICK_HORIZON_HOURS", "1")
    pred = attach_council_prediction(
        {"netuid": 11, "name": "SN11", "price": 2.0},
        {"confidence": 0.6, "signal_impact": {"net_direction": "up"}},
        0.6,
        horizon_type="day",
    )
    assert pred["horizon_hours"] == 24
    assert pred["horizon_type"] == "day"
    created = datetime.fromisoformat(pred["created_at"].replace("Z", "+00:00"))
    resolve_at = datetime.fromisoformat(pred["resolve_at"].replace("Z", "+00:00"))
    assert resolve_at - created == timedelta(hours=24)


def test_record_day_pick_ignores_preattached_short_horizon(monkeypatch, tmp_path):
    monkeypatch.setenv("ACC2_DAY_HORIZON_HOURS", "4")
    pred_path = tmp_path / "predictions.json"
    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(
        "internal.learning.prediction_loop.has_pending_duplicate", lambda *a, **k: False
    )
    subnet = {"netuid": 21, "name": "Test", "price": 1.5, "volume": 500000}
    pick = {
        "subnet": subnet,
        "score": 8.0,
        "confidence": 0.55,
        "final_confidence": 0.55,
        "expert_contributions": {"quant": 0.6},
        "prediction": {
            "predicted_pct": 3.0,
            "horizon_hours": 4,
            "horizon_type": "day",
            "magnitude_source": "preattached",
        },
    }
    row = record_pick_prediction(pick, subnet, horizon_type="day")
    assert row is not None
    assert row["horizon_hours"] == 24
    assert row["horizon_type"] == "day"
    created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
    resolve_at = datetime.fromisoformat(row["resolve_at"].replace("Z", "+00:00"))
    assert resolve_at - created == timedelta(hours=24)


def test_council_day_not_resolved_before_24h_window(tmp_path, monkeypatch):
    """Resolver must keep Council day picks pending until resolve_at."""
    cache = tmp_path / "price_cache.json"
    cache.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.resolver.PRICE_CACHE_PATH", str(cache))
    monkeypatch.setattr(
        "internal.council.price_reference.PRICE_CACHE_PATH", str(cache)
    )

    created = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
    resolve_at = created + timedelta(hours=24)
    pred = {
        "id": "council-day-1",
        "netuid": 42,
        "pick_source": "council",
        "horizon_type": "day",
        "horizon_hours": 24,
        "reference_price": 100.0,
        "predicted_pct": 5.0,
        "direction": "up",
        "created_at": created.isoformat().replace("+00:00", "Z"),
        "resolve_at": resolve_at.isoformat().replace("+00:00", "Z"),
        "status": "pending",
    }
    # Mid-window (12h) — must stay pending even with a live price.
    mid = created + timedelta(hours=12)
    out = resolve_prediction_at_horizon(pred, now=mid, live_prices={42: 110.0})
    assert out["status"] == "pending"
    assert out.get("resolved_price") is None

    # Still before resolve_at by 1 minute
    almost = resolve_at - timedelta(minutes=1)
    out2 = resolve_prediction_at_horizon(dict(pred), now=almost, live_prices={42: 110.0})
    assert out2["status"] == "pending"


def test_council_day_grace_uses_24h_multiple_not_1h(tmp_path, monkeypatch):
    """Expiry grace is horizon_hours * 2 — for day picks that is 48h, not 2h."""
    cache = tmp_path / "price_cache.json"
    cache.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.council.resolver.PRICE_CACHE_PATH", str(cache))
    monkeypatch.setattr(
        "internal.council.price_reference.PRICE_CACHE_PATH", str(cache)
    )

    created = datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc)
    resolve_at = created + timedelta(hours=24)
    pred = {
        "id": "council-day-grace",
        "netuid": 43,
        "pick_source": "council",
        "horizon_type": "day",
        "horizon_hours": 24,
        "reference_price": 100.0,
        "predicted_pct": 5.0,
        "direction": "up",
        "created_at": created.isoformat().replace("+00:00", "Z"),
        "resolve_at": resolve_at.isoformat().replace("+00:00", "Z"),
        "status": "pending",
    }
    # 2h after resolve_at would expire a 1h horizon (grace=2h) but NOT a 24h day pick
    # (grace=48h). Empty cache → stay pending inside grace, not expired.
    early_after = resolve_at + timedelta(hours=2)
    out = resolve_prediction_at_horizon(pred, now=early_after, live_prices={})
    assert out["status"] == "pending"
