"""Quality-first pump_lead backlog recovery (candle grades only)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from internal.learning.pump_lead_recover import (
    grade_pump_lead_at_resolve_candle,
    hydrate_candles_for_resolve,
    recover_overdue_pump_leads,
    sample_quality_ok,
)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def test_sample_quality_rejects_root_and_placeholder_stirring():
    ok, reason = sample_quality_ok(
        {
            "netuid": 0,
            "reference_price": 1.0,
            "pump_phase": "STIRRING",
            "pump_badge": "WARMING UP",
            "signal_snapshot": {"buy_ratio": 0.5, "volume_intensity": 1.0},
        }
    )
    assert ok is False
    assert "root" in reason or "invalid" in reason

    ok2, reason2 = sample_quality_ok(
        {
            "netuid": 28,
            "reference_price": 0.01,
            "pump_phase": "STIRRING",
            "pump_badge": "WARMING UP",
            "pump_claim": "STIRRING",
            "signal_snapshot": {"buy_ratio": 0.5, "volume_intensity": 1.0, "triad_strength": "WATCH"},
        }
    )
    assert ok2 is False
    assert "placeholder" in reason2 or "weak" in reason2


def test_sample_quality_accepts_building_with_flow():
    ok, _ = sample_quality_ok(
        {
            "netuid": 54,
            "reference_price": 0.02,
            "pump_phase": "ACCUMULATING",
            "pump_badge": "BUILDING",
            "pump_claim": "ACCUMULATING",
            "signal_snapshot": {
                "buy_ratio": 0.68,
                "volume_intensity": 0.4,
                "triad_strength": "BUILDING",
                "triad": {"inflow_quiet_load": True, "buy_pressure": True, "price_coil": False},
            },
        }
    )
    assert ok is True


def test_candle_grade_hit(tmp_path, monkeypatch):
    resolve_at = datetime(2026, 7, 23, 1, 0, tzinfo=timezone.utc)
    created = resolve_at - timedelta(hours=1)
    candles = []
    for i in range(-10, 11):
        ts = resolve_at + timedelta(minutes=i)
        candles.append(
            {
                "timestamp": _iso(ts),
                "close": 0.012,  # +20% vs ref 0.01
                "volume": 100,
            }
        )
    cache = {"54": {"candles": candles}}

    pred = {
        "id": "abc",
        "netuid": 54,
        "pick_source": "pump_lead",
        "reference_price": 0.01,
        "predicted_pct": 2.0,
        "pump_phase": "ACCUMULATING",
        "pump_badge": "BUILDING",
        "pump_claim": "ACCUMULATING",
        "created_at": _iso(created),
        "resolve_at": _iso(resolve_at),
        "status": "pending",
        "signal_snapshot": {"buy_ratio": 0.7, "volume_intensity": 0.5, "triad_strength": "STRONG"},
    }
    out = grade_pump_lead_at_resolve_candle(
        pred, now=resolve_at + timedelta(hours=3), cache=cache
    )
    assert out["status"] == "resolved"
    assert out["correct"] is True
    assert out["outcome"] == "hit"
    assert out["sample_quality"] == "high"
    assert out["price_source"] in {"vwap", "median", "median_no_volume"}


def test_recover_rejects_without_inventing_live_price(tmp_path, monkeypatch):
    pred_path = tmp_path / "predictions.json"
    resolve_at = datetime(2026, 7, 23, 1, 0, tzinfo=timezone.utc)
    pred_path.write_text(
        json.dumps(
            {
                "predictions": [
                    {
                        "id": "junk",
                        "netuid": 0,
                        "pick_source": "pump_lead",
                        "reference_price": 1.0,
                        "predicted_pct": 2.0,
                        "pump_phase": "STIRRING",
                        "pump_badge": "WARMING UP",
                        "pump_claim": "STIRRING",
                        "created_at": _iso(resolve_at - timedelta(hours=1)),
                        "resolve_at": _iso(resolve_at),
                        "status": "pending",
                        "signal_snapshot": {"buy_ratio": 0.5, "volume_intensity": 1.0},
                    }
                ],
                "resolved": [],
                "stats": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("internal.learning.pump_lead_recover.PREDICTIONS_PATH", str(pred_path))

    summary = recover_overdue_pump_leads(
        path=str(pred_path), dry_run=False, hydrate=False
    )
    assert summary["graded"] == 0
    assert summary["rejected_ungradeable"] == 1
    data = json.loads(Path(pred_path).read_text(encoding="utf-8"))
    assert data["predictions"] == []
    assert data["resolved"][0]["outcome"] == "ungradeable"
    assert data["resolved"][0].get("actual_pct") is None


def test_hydrate_skips_when_window_ready(tmp_path, monkeypatch):
    resolve_at = datetime(2026, 7, 23, 1, 0, tzinfo=timezone.utc)
    cache_path = tmp_path / "price_cache.json"
    candles = []
    for i in range(-10, 11):
        ts = resolve_at + timedelta(minutes=i)
        candles.append({"timestamp": _iso(ts), "close": 0.02, "volume": 10})
    cache_path.write_text(
        json.dumps({"54": {"candles": candles, "cached_at": 1e12, "source": "test"}}),
        encoding="utf-8",
    )
    calls = {"n": 0}

    def _boom(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("should not fetch when ready")

    monkeypatch.setattr(
        "internal.indicators.price_fetcher.fetch_ohlcv",
        _boom,
    )
    out = hydrate_candles_for_resolve(54, resolve_at, cache_path=str(cache_path))
    assert out["ready"] is True
    assert out["hydrated"] is False
    assert calls["n"] == 0


def test_hydrate_then_recover_grades(tmp_path, monkeypatch):
    resolve_at = datetime(2026, 7, 23, 1, 0, tzinfo=timezone.utc)
    created = resolve_at - timedelta(hours=1)
    pred_path = tmp_path / "predictions.json"
    cache_path = tmp_path / "price_cache.json"
    cache_path.write_text(json.dumps({}), encoding="utf-8")

    candles = []
    for i in range(-10, 11):
        ts = resolve_at + timedelta(minutes=i)
        candles.append({"timestamp": _iso(ts), "close": 0.012, "volume": 100})

    def fake_fetch(subnet_id, **_kwargs):
        data = {
            str(subnet_id): {
                "candles": candles,
                "cached_at": 1e12,
                "source": "test",
            }
        }
        cache_path.write_text(json.dumps(data), encoding="utf-8")
        return candles

    monkeypatch.setattr(
        "internal.indicators.price_fetcher.fetch_ohlcv", fake_fetch
    )
    monkeypatch.setattr(
        "internal.learning.pump_lead_recover.PRICE_CACHE_PATH", str(cache_path)
    )
    monkeypatch.setattr(
        "internal.council.price_reference.PRICE_CACHE_PATH", str(cache_path)
    )

    pred_path.write_text(
        json.dumps(
            {
                "predictions": [
                    {
                        "id": "good",
                        "netuid": 54,
                        "pick_source": "pump_lead",
                        "reference_price": 0.01,
                        "predicted_pct": 2.0,
                        "pump_phase": "ACCUMULATING",
                        "pump_badge": "BUILDING",
                        "pump_claim": "ACCUMULATING",
                        "created_at": _iso(created),
                        "resolve_at": _iso(resolve_at),
                        "status": "pending",
                        "signal_snapshot": {
                            "buy_ratio": 0.7,
                            "volume_intensity": 0.5,
                            "triad_strength": "STRONG",
                        },
                    }
                ],
                "resolved": [],
                "stats": {},
            }
        ),
        encoding="utf-8",
    )

    summary = recover_overdue_pump_leads(
        path=str(pred_path), dry_run=False, hydrate=True
    )
    assert summary["hydrate"]["attempted"] == 1
    assert summary["hydrate"]["ready"] == 1
    assert summary["graded"] == 1
    assert summary["hits"] == 1
    data = json.loads(pred_path.read_text(encoding="utf-8"))
    assert data["resolved"][0]["correct"] is True
    assert data["resolved"][0]["graded_via"] == "pump_lead_candle_recover"
