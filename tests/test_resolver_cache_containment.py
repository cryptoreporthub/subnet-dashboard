"""Containment tests for resolver price-cache snapshot reuse."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest

import internal.council.resolver as resolver


@pytest.fixture(autouse=True)
def isolate_data_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(tmp_path / "predictions.json"))
    monkeypatch.setattr(resolver, "PRICE_CACHE_PATH", str(tmp_path / "price_cache.json"))
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *_args, **_kwargs: True)


def _write_json(path: str, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)


def _candle(resolve_at: datetime, close: float) -> Dict[str, Any]:
    return {
        "timestamp": resolve_at.isoformat().replace("+00:00", "Z"),
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1000.0,
    }


def _cache(netuid: int, resolve_at: datetime, close: float = 110.0) -> Dict[str, Any]:
    return {str(netuid): {"candles": [_candle(resolve_at, close)]}}


def _prediction(
    pred_id: str,
    netuid: int,
    resolve_at: datetime,
    **extra: Any,
) -> Dict[str, Any]:
    prediction: Dict[str, Any] = {
        "id": pred_id,
        "netuid": netuid,
        "name": "Containment Test",
        "direction": "up",
        "predicted_pct": 2.0,
        "reference_price": 100.0,
        "resolve_at": resolve_at.isoformat().replace("+00:00", "Z"),
        "created_at": (resolve_at - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "status": "pending",
        "horizon_type": "hour",
        "horizon_hours": 1.0,
    }
    prediction.update(extra)
    return prediction


def _price_counter(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    original = resolver._load_json
    calls: List[str] = []

    def counting(path: str, *args: Any, **kwargs: Any) -> Any:
        if path == resolver.PRICE_CACHE_PATH:
            calls.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(resolver, "_load_json", counting)
    return calls


def _report_count(test_name: str, calls: List[str], expected: int) -> None:
    print(f"\n[TEST_CALL_COUNT] {test_name}: calls = {len(calls)}")
    assert len(calls) == expected


def test_lookup_with_explicit_cache_avoids_price_cache_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _price_counter(monkeypatch)
    resolve_at = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    prediction = _prediction("explicit-cache", 7, resolve_at)

    status, price, _meta = resolver.lookup_horizon_price(
        prediction,
        resolve_at=resolve_at,
        now=resolve_at + timedelta(minutes=5),
        cache=_cache(7, resolve_at),
    )

    assert status == "ok"
    assert price == pytest.approx(110.0)
    _report_count("test_lookup_with_explicit_cache_avoids_price_cache_read", calls, 0)


def test_regrade_nonempty_hydration_free_batch_loads_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _price_counter(monkeypatch)
    resolve_at = datetime.now(timezone.utc) - timedelta(hours=2)
    expired = _prediction(
        "regrade-once",
        7,
        resolve_at,
        status="expired",
        outcome="expired",
        retirement_reason="manual_expiry",
    )
    _write_json(resolver.PREDICTIONS_PATH, {"predictions": [], "resolved": [expired], "stats": {}})
    _write_json(resolver.PRICE_CACHE_PATH, _cache(7, resolve_at))
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", lambda *_args, **_kwargs: pytest.fail(
        "hydration should not run in the baseline regrade fixture"
    ))
    monkeypatch.setattr(
        resolver,
        "hydrate_candles_for_netuid_historical",
        lambda *_args, **_kwargs: pytest.fail(
            "historical hydration should not run in the baseline regrade fixture"
        ),
    )

    result = resolver.regrade_expired_predictions()

    assert result["regraded"] == 1
    _report_count("test_regrade_nonempty_hydration_free_batch_loads_once", calls, 1)


def test_regrade_empty_batch_does_not_load_price_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _price_counter(monkeypatch)
    _write_json(resolver.PREDICTIONS_PATH, {"predictions": [], "resolved": [], "stats": {}})

    result = resolver.regrade_expired_predictions()

    assert result["attempted"] == 0
    _report_count("test_regrade_empty_batch_does_not_load_price_cache", calls, 0)


def test_regrade_too_old_only_batch_retires_before_price_cache_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _price_counter(monkeypatch)
    resolve_at = datetime.now(timezone.utc) - timedelta(days=35)
    expired = _prediction(
        "too-old",
        7,
        resolve_at,
        status="expired",
        outcome="expired",
        retirement_reason="missing_price_at_horizon",
    )
    _write_json(resolver.PREDICTIONS_PATH, {"predictions": [], "resolved": [expired], "stats": {}})
    monkeypatch.setattr(
        resolver,
        "hydrate_candles_for_netuid_historical",
        lambda *_args, **_kwargs: None,
    )

    result = resolver.regrade_expired_predictions()

    assert result["attempted"] == 1
    with open(resolver.PREDICTIONS_PATH, encoding="utf-8") as handle:
        retired = json.load(handle)["resolved"][0]
    assert retired["retirement_reason"] == "horizon_too_old_for_history"
    _report_count("test_regrade_too_old_only_batch_retires_before_price_cache_load", calls, 0)


def test_resolve_due_predictions_uses_one_cycle_price_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _price_counter(monkeypatch)
    now = datetime.now(timezone.utc)
    resolve_at = now - timedelta(minutes=5)
    pending = _prediction("due-once", 7, resolve_at, horizon_hours=24.0)
    _write_json(resolver.PREDICTIONS_PATH, {"predictions": [pending], "resolved": [], "stats": {}})
    _write_json(resolver.PRICE_CACHE_PATH, _cache(7, resolve_at))
    monkeypatch.setattr(resolver, "_scenario_signals_for_subnet", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(resolver, "hydrate_candles_for_netuid", lambda *_args, **_kwargs: pytest.fail(
        "hydration should not run in the baseline resolve_due fixture"
    ))
    monkeypatch.setattr(
        resolver,
        "hydrate_candles_for_netuid_historical",
        lambda *_args, **_kwargs: pytest.fail(
            "historical hydration should not run in the baseline resolve_due fixture"
        ),
    )

    result = resolver._resolve_due_predictions(
        subnets=[
            {"netuid": 7, "price": 110.0},
            {"netuid": 8, "price": 210.0},
        ]
    )

    assert result["resolved_now"]
    _report_count("test_resolve_due_predictions_uses_one_cycle_price_snapshot", calls, 1)