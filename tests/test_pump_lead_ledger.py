"""Pump desk learning step 1 — pump_lead ledger at phase entry."""

from __future__ import annotations

import json

import pytest

from internal.council import resolver, weights
from internal.council.resolver import resolve_prediction
from internal.learning import predictions_store
from internal.learning.pump_lead_ledger import (
    gradeable_phase_entry,
    has_pending_pump_lead,
    record_pump_lead_at_phase_entry,
)
from internal.pump.state import transition_subnet


@pytest.fixture(autouse=True)
def isolate_predictions(tmp_path, monkeypatch):
    pred_path = str(tmp_path / "predictions.json")
    soul_path = str(tmp_path / "soul_map.json")
    soul_path_obj = tmp_path / "soul_map.json"
    soul_path_obj.write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "council_weights": {
                        "quant": 1.0,
                        "hype": 1.0,
                        "dark_horse": 1.0,
                        "technical": 1.0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", pred_path)
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", pred_path)
    monkeypatch.setattr(weights, "SOUL_MAP_PATH", soul_path)


def test_gradeable_phase_entry_lead_and_just_started():
    assert gradeable_phase_entry("STIRRING", 0.4) == "STIRRING"
    assert gradeable_phase_entry("ACCUMULATING", 0.6) == "ACCUMULATING"
    assert gradeable_phase_entry("PUMPING", 0.65) == "JUST_STARTED"
    assert gradeable_phase_entry("PUMPING", 0.85) is None
    assert gradeable_phase_entry("COOLING", 0.5) is None


def test_record_pump_lead_persists_frozen_claim():
    row = record_pump_lead_at_phase_entry(
        netuid=28,
        name="LOL",
        phase="ACCUMULATING",
        composite_score=0.62,
        reference_price=0.05,
        signal_snapshot={"buy_ratio": 0.7, "volume_intensity": 0.4, "price": 0.05},
    )
    assert row is not None
    assert row["pick_source"] == "pump_lead"
    assert row["predicted_pct"] == 2.0
    assert row["horizon_type"] == "pump_lead"
    assert row["horizon_hours"] == 1
    assert row["signal_snapshot"]["buy_ratio"] == 0.7
    assert has_pending_pump_lead(28) is True

    data = predictions_store.load_predictions()
    assert len(data["predictions"]) == 1
    assert data["predictions"][0]["pump_badge"] == "BUILDING"


def test_record_pump_lead_dedupes_pending_same_netuid():
    first = record_pump_lead_at_phase_entry(
        netuid=7,
        name="SN7",
        phase="STIRRING",
        composite_score=0.3,
        reference_price=1.0,
        signal_snapshot={"buy_ratio": 0.6},
    )
    second = record_pump_lead_at_phase_entry(
        netuid=7,
        name="SN7",
        phase="ACCUMULATING",
        composite_score=0.5,
        reference_price=1.0,
        signal_snapshot={"buy_ratio": 0.7},
    )
    assert first is not None
    assert second is None
    assert len(predictions_store.load_predictions()["predictions"]) == 1


def test_transition_subnet_records_pump_lead_on_phase_entry():
    state = {"subnets": {}, "meta": {}}
    signals = {
        "netuid": 54,
        "name": "WebGenieAI",
        "price": 0.12,
        "price_change_24h": 0.04,
        "momentum_1h": 0.01,
        "volume_intensity": 0.35,
        "buy_ratio": 0.58,
        "chatter_intensity": 0.1,
    }
    _event, changed = transition_subnet(state, signals)
    assert changed is True
    pending = predictions_store.load_predictions()["predictions"]
    assert len(pending) == 1
    assert pending[0]["pick_source"] == "pump_lead"
    assert pending[0]["netuid"] == 54


def test_resolver_skips_council_weight_nudge_for_pump_lead(monkeypatch):
    before = dict(weights.load_weights())
    pred = {
        "id": "pump1",
        "netuid": 1,
        "direction": "up",
        "predicted_pct": 2.0,
        "reference_price": 100.0,
        "horizon_hours": 1,
        "horizon_type": "pump_lead",
        "pick_source": "pump_lead",
        "pump_claim": "ACCUMULATING",
        "expert": "quant",
        "resolve_at": "2099-01-01T00:00:00Z",
        "status": "pending",
    }
    resolve_prediction(pred, current_price=103.0)
    after = dict(weights.load_weights())
    assert before == after
    assert pred.get("correct") is True
