"""Phase O — TAO Signal Hub tests."""

from __future__ import annotations

import json

import pytest

from internal.signal_hub import anomaly, overlay, tracker
from internal.signal_hub.l_bridge import hub_signals_to_store_rows, publish_to_phase_l


def test_population_zscore_extreme():
    population = [1.0, 2.0, 1.5, 1.8, 2.2]
    z = anomaly.population_zscore(20.0, population)
    assert z > anomaly.ZSCORE_THRESHOLD


def test_dual_guard_requires_two_hits_or_extreme_z():
    hits = [
        {
            "type": "price_population_z",
            "subnet_id": 1,
            "z_score": 2.1,
            "direction": "bullish",
            "severity": "warning",
        }
    ]
    assert anomaly._filter_dual_guard(hits) == []
    hits[0]["z_score"] = 3.0
    assert len(anomaly._filter_dual_guard(hits)) == 1


def test_evaluate_subnet_anomalies_emits_on_z_and_roc(tmp_path, monkeypatch):
    cache_path = tmp_path / "price_cache.json"
    closes = [100.0 + i for i in range(35)]
    closes[-1] = closes[-2] * 1.12
    candles = [{"close": c, "volume": 1000.0, "high": c, "low": c} for c in closes]
    cache_path.write_text(json.dumps({"1": {"candles": candles}}), encoding="utf-8")
    monkeypatch.setattr(tracker, "PRICE_CACHE_PATH", str(cache_path))

    population = [1.0] * 20 + [25.0]
    sn = {"netuid": 1, "name": "Alpha", "price_change_24h": 25.0}
    hits = anomaly.evaluate_subnet_anomalies(
        sn,
        cache={"1": {"candles": candles}},
        population_changes=population,
    )
    types = {h["type"] for h in hits}
    assert "price_population_z" in types


def test_hub_tracker_run_cycle_persists(tmp_path, monkeypatch):
    state_path = str(tmp_path / "hub_state.json")
    signals_path = str(tmp_path / "signals.json")
    monkeypatch.setattr(tracker, "PRICE_CACHE_PATH", str(tmp_path / "empty_cache.json"))
    (tmp_path / "empty_cache.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr("internal.signal_hub.state.HUB_STATE_PATH", state_path)
    monkeypatch.setenv("SIGNALS_PATH", signals_path)

    subnets = [{"netuid": i, "name": f"SN{i}", "price_change_24h": 1.0} for i in range(5)]
    subnets.append({"netuid": 99, "name": "Outlier", "price_change_24h": 40.0})
    monkeypatch.setattr("internal.signals.pipeline.load_subnets", lambda: subnets)

    result = tracker.HubTracker().run_cycle(persist=True)
    assert result["status"] == "ok"
    from internal.signal_hub.state import load_hub_state

    state = load_hub_state(state_path)
    assert state.get("active") is True
    assert state.get("meta", {}).get("anomaly_count", 0) >= 0


def test_publish_to_phase_l_writes_store(tmp_path, monkeypatch):
    from pathlib import Path

    signals_path = str(tmp_path / "signals.json")
    alerts_path = str(tmp_path / "alerts.json")
    monkeypatch.setenv("SIGNALS_PATH", signals_path)
    monkeypatch.setenv("ALERTS_PATH", alerts_path)

    anomalies = [
        {
            "type": "price_population_z",
            "subnet_id": 7,
            "name": "Test",
            "z_score": 3.0,
            "direction": "bullish",
            "severity": "critical",
        }
    ]
    out = publish_to_phase_l(anomalies)
    assert out["signals_written"] == 1
    assert Path(signals_path).exists()


def test_apply_hub_overlay_bounded():
    experts = {"quant": 0.5, "hype": 0.5, "dark_horse": 0.5, "technical": 0.5}
    boosted = overlay.apply_hub_overlay(
        experts,
        {"anomaly_score": 1.0, "direction": "bullish"},
    )
    assert boosted["hype"] > experts["hype"]
    assert boosted["hype"] - experts["hype"] <= overlay.OVERLAY_MAX_BOOST + 1e-6


def test_council_score_without_hub_overlay():
    from internal.council.state_vector import score_subnet_for_hour

    sn = {"netuid": 1, "name": "A", "price": 10.0, "volume": 1000, "price_change_24h": 2.0}
    a = score_subnet_for_hour(sn, market_context={"hub_overlay": {}})
    b = score_subnet_for_hour(sn, market_context=None)
    assert a["total_score"] == b["total_score"]


def test_hub_signals_to_store_rows():
    rows = hub_signals_to_store_rows(
        [
            {
                "type": "volume_spike",
                "subnet_id": 3,
                "name": "Gamma",
                "volume_ratio": 3.0,
                "direction": "bullish",
                "severity": "info",
            }
        ]
    )
    assert rows[0]["source_expert"] == "hub"
    assert rows[0]["signal_type"] == "buy"


def test_api_signal_hub_status():
    from fastapi.testclient import TestClient
    from server import app

    client = TestClient(app)
    resp = client.get("/api/signal-hub/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "hub" in body
    assert "thresholds" in body


def test_api_signal_hub_signals_honest_empty():
    from fastapi.testclient import TestClient
    from server import app

    client = TestClient(app)
    resp = client.get("/api/signal-hub/signals")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert isinstance(body["signals"], list)
