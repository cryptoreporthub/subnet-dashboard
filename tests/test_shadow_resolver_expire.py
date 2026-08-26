"""Site A — shadow/counterfactual rows past grace must retire, not block watchdog."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from internal.council import resolver
from internal.council.watchdog import check_resolver_watchdog


def test_shadow_past_grace_expires_in_resolve_due_without_late_grade(tmp_path, monkeypatch):
    """Shadow rows skip council late-grade hydrate and move to resolved expired."""
    path = tmp_path / "predictions.json"
    resolve_at = datetime(2026, 8, 26, 1, 9, 51, tzinfo=timezone.utc)
    now = resolve_at + timedelta(hours=4)
    pred = {
        "id": "dd13cfb298",
        "netuid": 29,
        "direction": "down",
        "predicted_pct": -0.12,
        "horizon_hours": 1,
        "horizon_type": "hour",
        "reference_price": 0.00279681,
        "created_at": "2026-08-26T00:09:51.954177Z",
        "resolve_at": resolve_at.isoformat().replace("+00:00", "Z"),
        "status": "pending",
        "shadow": True,
        "counterfactual": True,
        "price_data_unavailable": True,
    }
    path.write_text(json.dumps({"predictions": [pred], "resolved": [], "stats": {}}), encoding="utf-8")
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(path))
    monkeypatch.setattr(resolver, "PRICE_CACHE_PATH", str(tmp_path / "price_cache.json"))
    monkeypatch.setattr(resolver, "fetch_prices", lambda _s: {})
    monkeypatch.setattr(
        resolver,
        "regrade_expired_predictions",
        lambda **kw: {"regraded": 0, "ledger_mutated": False},
    )
    monkeypatch.setattr(resolver, "_restore_recently_expired_predictions", lambda *a, **k: [])

    with patch.object(resolver, "hydrate_candles_for_netuid") as mock_hydrate:
        out = resolver.resolve_due_predictions(subnets=[{"netuid": 29, "price": 1.0}])
        mock_hydrate.assert_not_called()

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["predictions"] == []
    assert saved["resolved"][0]["id"] == "dd13cfb298"
    assert saved["resolved"][0]["status"] == "expired"
    assert saved["resolved"][0]["retirement_reason"] == "missing_price_at_horizon"
    assert out["watchdog"]["warning"] is False


def test_watchdog_ignores_shadow_pending_past_grace():
    resolve_at = datetime(2026, 8, 26, 1, 9, 51, tzinfo=timezone.utc)
    now = resolve_at + timedelta(hours=4)
    pending = [
        {
            "id": "dd13cfb298",
            "resolve_at": resolve_at.isoformat().replace("+00:00", "Z"),
            "horizon_hours": 1,
            "shadow": True,
            "counterfactual": True,
        }
    ]
    status = check_resolver_watchdog(pending, now=now)
    assert status["warning"] is False


def test_watchdog_hour_type_fallback_when_horizon_hours_missing():
    resolve_at = datetime(2026, 8, 26, 1, 9, 51, tzinfo=timezone.utc)
    now = resolve_at + timedelta(hours=2, minutes=5)
    pending = [
        {
            "id": "council-1",
            "resolve_at": resolve_at.isoformat().replace("+00:00", "Z"),
            "horizon_type": "hour",
        }
    ]
    status = check_resolver_watchdog(pending, now=now)
    assert status["warning"] is True
    assert status["threshold_hours"] == 2.0
