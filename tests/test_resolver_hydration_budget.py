"""Regression coverage for bounded resolver cache-miss hydration."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import internal.council.price_reference as price_reference
import internal.council.resolver as resolver
import internal.council.weights as weights


def _write_predictions(path, rows):
    path.write_text(
        json.dumps({"predictions": rows, "resolved": [], "stats": {}}),
        encoding="utf-8",
    )


def _due_prediction(netuid: int, now: datetime) -> dict:
    return {
        "id": f"budget-{netuid}",
        "netuid": netuid,
        "reference_price": 100.0,
        "predicted_pct": 1.0,
        "direction": "up",
        "horizon_hours": 24.0,
        "resolve_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }


def test_resolve_due_caps_unique_cache_miss_hydration(monkeypatch, tmp_path):
    predictions_path = tmp_path / "predictions.json"
    price_cache_path = tmp_path / "price_cache.json"
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(predictions_path))
    monkeypatch.setattr(resolver, "PRICE_CACHE_PATH", str(price_cache_path))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(tmp_path / "soul_map.json"))
    monkeypatch.setattr(resolver, "_RESOLVER_HYDRATION_MAX", 4)
    monkeypatch.setenv("CALIBRATION_HYDRATE_ON_MISS", "true")
    price_reference._hydrate_memo.clear()
    calls = []

    def _fake_fetch(netuid, **_kwargs):
        calls.append(str(netuid))
        return []

    monkeypatch.setattr("internal.indicators.price_fetcher.fetch_ohlcv", _fake_fetch)
    now = datetime.now(timezone.utc)
    _write_predictions(
        predictions_path,
        [_due_prediction(netuid, now) for netuid in range(700, 706)],
    )

    result = resolver.resolve_due_predictions(subnets=[])

    assert calls == ["700", "701", "702", "703"]
    assert len(result["pending"]) == 6
    assert result["resolved_now"] == []


def test_resolve_budget_does_not_block_existing_candle(monkeypatch, tmp_path):
    predictions_path = tmp_path / "predictions.json"
    price_cache_path = tmp_path / "price_cache.json"
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(predictions_path))
    monkeypatch.setattr(resolver, "PRICE_CACHE_PATH", str(price_cache_path))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(tmp_path / "soul_map.json"))
    monkeypatch.setattr(resolver, "_RESOLVER_HYDRATION_MAX", 0)
    monkeypatch.setenv("CALIBRATION_HYDRATE_ON_MISS", "true")
    price_reference._hydrate_memo.clear()
    monkeypatch.setattr(resolver, "_stamp_and_nudge_expert", lambda *_a, **_k: (None, None))
    monkeypatch.setattr(resolver, "_nudge_impact_strength", lambda *_a, **_k: None)
    monkeypatch.setattr(resolver, "_record_scenario_outcome", lambda *_a, **_k: None)
    monkeypatch.setattr(resolver, "_nudge_signal_weights", lambda *_a, **_k: None)

    def _fake_finalize(prediction, **kwargs):
        prediction.update(
            {
                "status": "resolved",
                "outcome": kwargs["outcome"],
                "correct": kwargs["correct"],
                "resolved_price": kwargs["resolved_price"],
                "resolved_at": kwargs["resolved_at"],
            }
        )
        return prediction

    monkeypatch.setattr(resolver, "atomic_finalize_resolution", _fake_finalize)
    now = datetime.now(timezone.utc)
    resolve_at = now - timedelta(hours=1)
    _write_predictions(predictions_path, [_due_prediction(706, now)])
    price_cache_path.write_text(
        json.dumps(
            {
                "706": {
                    "candles": [
                        {
                            "timestamp": resolve_at.isoformat().replace("+00:00", "Z"),
                            "close": 101.0,
                            "volume": 1.0,
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = resolver.resolve_due_predictions(subnets=[])

    assert len(result["resolved_now"]) == 1
    assert result["pending"] == []
