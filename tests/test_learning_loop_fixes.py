"""Tests for the accelerated learning-loop fixes.

Covers:
- Granular scenario tags (volume buckets, tightened RSI bands, neutral regime
  direction split, ``price_direction`` field)
- Scenario memory ``update_outcome`` / ``record_outcome`` outcome wiring
- Resolver writes outcomes back to existing scenario records
- ``/api/learning/trigger`` endpoint runs a resolver cycle
- Resolver scheduler default interval is 15 minutes
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import internal.council.resolver as resolver
import internal.council.resolver_scheduler as resolver_scheduler
import internal.council.scenario_memory as scenario_memory
import internal.council.weights as weights
from internal.council.state_vector import _scenario_tags


@pytest.fixture(autouse=True)
def isolate_data_paths(tmp_path, monkeypatch):
    """Keep all persistence inside a temp directory."""
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(tmp_path / "predictions.json"))
    monkeypatch.setattr(resolver, "PRICE_CACHE_PATH", str(tmp_path / "price_cache.json"))
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", str(tmp_path / "soul_map.json"))
    monkeypatch.setattr(resolver_scheduler, "SOUL_MAP_PATH", str(tmp_path / "soul_map.json"))
    monkeypatch.setattr(scenario_memory, "SCENARIO_MEMORY_PATH", str(tmp_path / "scenario_memory.json"))


@pytest.fixture
def nudge_spy(monkeypatch):
    calls = []

    def _fake_nudge(correct, expert):
        calls.append((correct, expert))

    monkeypatch.setattr(resolver, "_nudge_weights", _fake_nudge)
    return calls


# ---------------------------------------------------------------------------
# Fix 1 — granular scenario tags
# ---------------------------------------------------------------------------

def test_scenario_tags_keys_include_price_direction():
    tags = _scenario_tags({"volume": 600_000, "price_change_24h": 1.2}, {}, {"tao_change_24h": 0.5})
    assert set(tags.keys()) == {"regime", "rsi", "volume", "price_direction", "valuation"}


def test_scenario_tags_volume_buckets():
    assert _scenario_tags({"volume": 100}, {}, {})["volume"] == "very_low"
    assert _scenario_tags({"volume": 1_000}, {}, {})["volume"] == "low"
    assert _scenario_tags({"volume": 10_000}, {}, {})["volume"] == "medium"
    assert _scenario_tags({"volume": 60_000}, {}, {})["volume"] == "high"


def test_scenario_tags_rsi_bands_tightened():
    # 35 and 65 are the new neutral boundaries.
    assert _scenario_tags({}, {"rsi": {"value": 34}}, {})["rsi"] == "oversold"
    assert _scenario_tags({}, {"rsi": {"value": 35}}, {})["rsi"] == "neutral"
    assert _scenario_tags({}, {"rsi": {"value": 65}}, {})["rsi"] == "neutral"
    assert _scenario_tags({}, {"rsi": {"value": 66}}, {})["rsi"] == "overbought"


def test_scenario_tags_neutral_regime_direction_split():
    assert _scenario_tags({"price_change_24h": 0.5}, {}, {"tao_change_24h": 1.0})["regime"] == "neutral_bullish"
    assert _scenario_tags({"price_change_24h": -0.5}, {}, {"tao_change_24h": -1.0})["regime"] == "neutral_bearish"
    assert _scenario_tags({"price_change_24h": 0}, {}, {"tao_change_24h": 0})["regime"] == "neutral"
    # Strong moves still classify as bullish/bearish.
    assert _scenario_tags({}, {}, {"tao_change_24h": 5.0})["regime"] == "bullish"
    assert _scenario_tags({}, {}, {"tao_change_24h": -5.0})["regime"] == "bearish"


def test_scenario_tags_price_direction_field():
    assert _scenario_tags({"price_change_24h": 2.0}, {}, {})["price_direction"] == "up"
    assert _scenario_tags({"price_change_24h": -2.0}, {}, {})["price_direction"] == "down"
    assert _scenario_tags({"price_change_24h": 0}, {}, {})["price_direction"] == "up"


# ---------------------------------------------------------------------------
# Fix 3 — scenario memory outcome wiring
# ---------------------------------------------------------------------------

def test_update_outcome_stamps_existing_record():
    created = scenario_memory.add_scenario(
        name="Subnet A", features={"direction": "up"}, outcome=None
    )
    updated = scenario_memory.update_outcome(created["id"], "correct", metadata={"actual_pct": 3.1})
    assert updated is not None
    assert updated["outcome"] == "correct"
    assert updated["resolved_at"] is not None
    assert updated["metadata"]["actual_pct"] == 3.1


def test_update_outcome_returns_none_for_missing_id():
    assert scenario_memory.update_outcome("does_not_exist", "correct") is None


def test_record_outcome_wires_back_to_pending_scenario():
    pending = scenario_memory.add_scenario(
        name="Subnet B", features={"direction": "up"}, outcome=None
    )
    result = scenario_memory.record_outcome(
        name="Subnet B", outcome="correct", features={"direction": "up"}
    )
    # The outcome should land on the existing pending record, not a new one.
    assert result["id"] == pending["id"]
    assert result["outcome"] == "correct"
    snapshot = scenario_memory.get_memory_snapshot()
    assert len(snapshot["scenarios"]) == 1


def test_record_outcome_creates_new_when_no_pending_match():
    result = scenario_memory.record_outcome(
        name="Subnet C", outcome="wrong", features={"direction": "down"}
    )
    assert result["outcome"] == "wrong"
    assert scenario_memory.get_memory_snapshot()["stats"]["total"] == 1


def test_resolver_writes_outcome_back_to_linked_scenario():
    # Mint a pending scenario and link it to a prediction, then resolve.
    pending = scenario_memory.add_scenario(
        name="Subnet D", features={"direction": "up"}, outcome=None
    )
    now = datetime.now(timezone.utc)
    prediction = {
        "netuid": 1,
        "name": "Subnet D",
        "direction": "up",
        "predicted_pct": 2.0,
        "reference_price": 10.0,
        "expert": "quant",
        "scenario_id": pending["id"],
        "resolve_at": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    }
    resolver.resolve_prediction(prediction, current_price=10.5)
    # The linked scenario record should now carry the resolved outcome.
    snapshot = scenario_memory.get_memory_snapshot()
    linked = [s for s in snapshot["scenarios"] if s["id"] == pending["id"]]
    assert linked and linked[0]["outcome"] == "correct"


# ---------------------------------------------------------------------------
# Fix 4 — accelerated learning loop
# ---------------------------------------------------------------------------

def test_resolver_default_refresh_minutes_is_15():
    assert resolver_scheduler.RESOLVER_REFRESH_MINUTES == 15


def test_learning_trigger_endpoint_runs_cycle():
    from server import app

    client = TestClient(app)
    response = client.post("/api/learning/trigger")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "cycle" in data["data"]
    assert "scheduler" in data["data"]
    assert "triggered_at" in data["data"]
