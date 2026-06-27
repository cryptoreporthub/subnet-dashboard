"""
Unit + integration tests for Phase 2 of the modular state-vector Council engine.

Covers:
- 24h prediction resolution (resolver)
- Regime-aware scenario memory persistence (scenario_memory)
- Subnet rotation / volatility clustering (rotation_tracker)
- New server endpoints wired to the modules above
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

import internal.council.resolver as resolver
import internal.council.scenario_memory as scenario_memory
import internal.council.rotation_tracker as rotation_tracker
import internal.council.weights as weights


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_data_paths(tmp_path, monkeypatch):
    """Keep all Phase 2 persistence inside a temp directory."""
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(tmp_path / "predictions.json"))
    monkeypatch.setattr(resolver, "PRICE_CACHE_PATH", str(tmp_path / "price_cache.json"))
    monkeypatch.setattr(scenario_memory, "SCENARIO_MEMORY_PATH", str(tmp_path / "scenario_memory.json"))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(tmp_path / "soul_map.json"))


@pytest.fixture
def nudge_spy(monkeypatch):
    """Capture weight nudges without touching the filesystem."""
    calls = []

    def _fake_nudge(correct, expert):
        calls.append((correct, expert))

    monkeypatch.setattr(resolver, "_nudge_weights", _fake_nudge)
    return calls


# ---------------------------------------------------------------------------
# Resolver tests
# ---------------------------------------------------------------------------

def test_fetch_prices_from_subnets():
    subnets = [
        {"netuid": 1, "price": 10.0},
        {"netuid": 2, "price": 20.0},
        {"netuid": 3, "price": 0.0},
    ]
    prices = resolver.fetch_prices(subnets)
    assert prices == {1: 10.0, 2: 20.0}


def test_fetch_prices_fallback_to_cache(tmp_path, isolate_data_paths):
    cache = {
        "1": {"candles": [{"close": 5.0}, {"close": 7.0}]},
        "2": {"candles": []},
    }
    with open(resolver.PRICE_CACHE_PATH, "w") as f:
        json.dump(cache, f)
    prices = resolver.fetch_prices([])
    # Cache keys remain strings; values are parsed as floats.
    assert prices == {"1": 7.0}


def test_classify_outcome_up_hit():
    pred = {"reference_price": 100.0, "predicted_pct": 10.0, "direction": "up"}
    assert resolver.classify_outcome(pred, 115.0) == "hit"


def test_classify_outcome_up_partial():
    pred = {"reference_price": 100.0, "predicted_pct": 10.0, "direction": "up"}
    assert resolver.classify_outcome(pred, 102.0) == "partial"


def test_classify_outcome_up_miss():
    pred = {"reference_price": 100.0, "predicted_pct": 10.0, "direction": "up"}
    assert resolver.classify_outcome(pred, 95.0) == "miss"


def test_classify_outcome_down_hit_and_miss():
    pred = {"reference_price": 100.0, "predicted_pct": -10.0, "direction": "down"}
    assert resolver.classify_outcome(pred, 92.0) == "hit"
    assert resolver.classify_outcome(pred, 98.0) == "partial"
    assert resolver.classify_outcome(pred, 105.0) == "miss"


def test_resolve_prediction_updates_fields(nudge_spy):
    pred = {
        "netuid": 5,
        "reference_price": 100.0,
        "predicted_pct": 10.0,
        "direction": "up",
        "expert": "quant",
    }
    resolved = resolver.resolve_prediction(pred, 115.0)
    assert resolved["status"] == "resolved"
    assert resolved["outcome"] == "hit"
    assert resolved["correct"] is True
    assert resolved["actual_pct"] == 15.0
    assert "resolved_at" in resolved
    assert nudge_spy == [(True, "quant")]


def test_resolve_due_predictions_resolves_only_due(nudge_spy):
    now = datetime.now(timezone.utc)
    data = {
        "predictions": [
            {
                "netuid": 1,
                "reference_price": 100.0,
                "predicted_pct": 10.0,
                "direction": "up",
                "expert": "hype",
                "resolve_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            },
            {
                "netuid": 2,
                "reference_price": 100.0,
                "predicted_pct": 10.0,
                "direction": "up",
                "expert": "technical",
                "resolve_at": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            },
        ],
        "resolved": [],
    }
    with open(resolver.PREDICTIONS_PATH, "w") as f:
        json.dump(data, f)

    subnets = [{"netuid": 1, "price": 110.0}, {"netuid": 2, "price": 105.0}]
    result = resolver.resolve_due_predictions(subnets)

    assert len(result["resolved_now"]) == 1
    assert result["resolved_now"][0]["netuid"] == 1
    assert result["pending"][0]["netuid"] == 2
    assert result["stats"]["pending"] == 1
    assert nudge_spy == [(True, "hype")]


def test_get_resolved_predictions():
    data = {
        "predictions": [],
        "resolved": [
            {"correct": True},
            {"correct": True},
            {"correct": False},
        ],
    }
    with open(resolver.PREDICTIONS_PATH, "w") as f:
        json.dump(data, f)

    result = resolver.get_resolved_predictions()
    assert len(result["resolved"]) == 3
    assert result["stats"]["correct"] == 2
    assert result["stats"]["wrong"] == 1
    assert result["stats"]["accuracy"] == round(2 / 3, 3)


# ---------------------------------------------------------------------------
# Scenario memory tests
# ---------------------------------------------------------------------------

def test_classify_regime_from_features():
    assert scenario_memory.classify_regime({"avg_change_24h": 10.0}) == "volatile"
    assert scenario_memory.classify_regime({"avg_change_24h": 5.0, "breadth": "bullish"}) == "bull"
    assert scenario_memory.classify_regime({"avg_change_24h": -5.0, "breadth": "bearish"}) == "bear"
    assert scenario_memory.classify_regime({"avg_change_24h": 1.0, "volatility": 2.0}) == "neutral"


def test_add_scenario_persists(tmp_path):
    scenario = scenario_memory.add_scenario(
        name="test_bull",
        features={"avg_change_24h": 6.0},
        outcome="hit",
    )
    assert scenario["name"] == "test_bull"
    assert scenario["regime"] == "bull"
    assert os.path.exists(scenario_memory.SCENARIO_MEMORY_PATH)

    with open(scenario_memory.SCENARIO_MEMORY_PATH, "r") as f:
        data = json.load(f)
    assert len(data["scenarios"]) == 1
    assert scenario["id"] in data["regimes"]["bull"]
    assert "last_updated" in data["meta"]


def test_get_scenarios_filter_and_limit():
    scenario_memory.add_scenario("a", {"avg_change_24h": 6.0}, outcome="hit")
    scenario_memory.add_scenario("b", {"avg_change_24h": -6.0}, outcome="miss")
    scenario_memory.add_scenario("c", {"avg_change_24h": 7.0}, outcome="hit")

    bull = scenario_memory.get_scenarios(regime="bull")
    assert len(bull) == 2
    assert all(s["regime"] == "bull" for s in bull)

    limited = scenario_memory.get_scenarios(limit=1)
    assert len(limited) == 1
    assert limited[0]["name"] == "c"


def test_get_regime_stats():
    scenario_memory.add_scenario("s1", {"avg_change_24h": 6.0}, outcome="hit")
    scenario_memory.add_scenario("s2", {"avg_change_24h": 6.5}, outcome="hit")
    scenario_memory.add_scenario("s3", {"avg_change_24h": -6.0}, outcome="miss")

    stats = scenario_memory.get_regime_stats()
    assert stats["total"] == 3
    assert stats["by_regime"]["bull"] == 2
    assert stats["by_regime"]["bear"] == 1
    assert stats["accuracy"]["bull"] == 1.0
    assert stats["accuracy"]["bear"] == 0.0


def test_get_memory_snapshot():
    snapshot = scenario_memory.get_memory_snapshot()
    assert set(snapshot.keys()) == {"scenarios", "regimes", "stats", "meta"}
    assert snapshot["regimes"] == {r: [] for r in scenario_memory.REGIMES}


# ---------------------------------------------------------------------------
# Rotation tracker tests
# ---------------------------------------------------------------------------

def test_cluster_by_volatility():
    subnets = [
        {"netuid": 1, "price_change_24h": 1.0, "price_change_7d": 7.0},
        {"netuid": 2, "price_change_24h": 2.0, "price_change_7d": 14.0},
        {"netuid": 3, "price_change_24h": 10.0, "price_change_7d": 70.0},
        {"netuid": 4, "price_change_24h": 12.0, "price_change_7d": 84.0},
    ]
    clusters = rotation_tracker.cluster_by_volatility(subnets)
    assert clusters["summary"]["count"] == 4
    assert len(clusters["high"]) >= 1
    assert len(clusters["low"]) >= 1
    assert len(clusters["core"]) >= 0


def test_detect_rotation_patterns():
    subnets = [
        {"netuid": 1, "price_change_24h": 5.0, "volume": 2_000_000, "apy": 10.0, "emission": 1.0},
        {"netuid": 2, "price_change_24h": 4.0, "volume": 1_500_000, "apy": 12.0, "emission": 1.0},
        {"netuid": 3, "price_change_24h": -5.0, "volume": 500_000, "apy": 12.0, "emission": 1.0},
    ]
    patterns = rotation_tracker.detect_rotation_patterns(subnets)
    assert isinstance(patterns, list)
    assert all("confidence" in p and "pattern" in p for p in patterns)
    # Sorted by descending confidence.
    assert patterns == sorted(patterns, key=lambda p: p["confidence"], reverse=True)


def test_get_rotation_summary():
    summary = rotation_tracker.get_rotation_summary([])
    assert "timestamp" in summary
    assert summary["patterns"] == []
    assert summary["volatility_clusters"]["summary"]["count"] == 0


# ---------------------------------------------------------------------------
# Server endpoint tests
# ---------------------------------------------------------------------------

def test_server_scenario_memory_endpoints(monkeypatch):
    from server import app
    from fastapi.testclient import TestClient

    # Use the isolated tmp path already configured by autouse fixture.
    client = TestClient(app)

    get_resp = client.get("/api/scenario-memory")
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "ok"

    post_resp = client.post(
        "/api/scenario-memory",
        json={"name": "server_test", "features": {"avg_change_24h": 6.0}, "outcome": "hit"},
    )
    assert post_resp.status_code == 200
    body = post_resp.json()
    assert body["status"] == "ok"
    assert body["scenario"]["regime"] == "bull"

    get_resp2 = client.get("/api/scenario-memory")
    assert len(get_resp2.json()["scenarios"]) == 1


def test_server_rotation_tracker_endpoint():
    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    resp = client.get("/api/rotation-tracker")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "patterns" in body
    assert "volatility_clusters" in body


def test_server_predictions_resolved_endpoint(nudge_spy):
    from server import app
    from fastapi.testclient import TestClient

    client = TestClient(app)

    resp = client.get("/api/predictions/resolved")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    # Use netuid 29 because the static fallback used by the server includes it.
    now = datetime.now(timezone.utc)
    data = {
        "predictions": [
            {
                "netuid": 29,
                "reference_price": 20.0,
                "predicted_pct": 5.0,
                "direction": "up",
                "expert": "quant",
                "resolve_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            }
        ],
        "resolved": [],
    }
    with open(resolver.PREDICTIONS_PATH, "w") as f:
        json.dump(data, f)

    resp = client.get("/api/predictions/resolved?resolve=1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["triggered_resolution"] is True
    assert len(body["resolved"]) == 1
    assert body["resolved"][0]["outcome"] == "hit"
