"""Claim-time feature freeze + Upgrade-6 train stub."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from internal.learning.pump_lead_features import (
    FEATURE_KEYS,
    FEATURE_SCHEMA_VERSION,
    attach_frozen_features,
    feature_row_from_prediction,
    freeze_feature_vector,
)
from internal.learning.pump_lead_ledger import record_pump_lead_at_phase_entry
from internal.learning.pump_lead_train import (
    MIN_TRAIN_SAMPLES,
    collect_training_rows,
    dataset_status,
    export_train_matrix,
    train_offline,
)
from internal.learning import predictions_store


def test_freeze_feature_vector_schema_v1():
    vec = freeze_feature_vector(
        {
            "buy_ratio": 0.68,
            "volume_intensity": 0.4,
            "price_change_24h": 0.03,
            "momentum_1h": 0.01,
            "chatter_intensity": 0.2,
            "triad": {
                "inflow_quiet_load": True,
                "buy_pressure": True,
                "price_coil": False,
            },
        },
        composite_score=0.55,
        created_at="2026-07-23T14:30:00Z",
        prediction={"pump_claim": "ACCUMULATING"},
    )
    assert set(vec.keys()) == set(FEATURE_KEYS)
    assert vec["buy_ratio"] == 0.68
    assert vec["triad_lit_count"] == 2.0
    assert vec["hour_utc"] == 14.0
    assert vec["phase_code"] == 2.0
    assert vec["composite_score"] == 0.55


def test_ledger_attaches_frozen_feature_vector(tmp_path, monkeypatch):
    pred_path = str(tmp_path / "predictions.json")
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", pred_path)
    row = record_pump_lead_at_phase_entry(
        netuid=54,
        name="WebGenieAI",
        phase="ACCUMULATING",
        composite_score=0.61,
        reference_price=0.02,
        signal_snapshot={
            "buy_ratio": 0.7,
            "volume_intensity": 0.45,
            "price_change_24h": 0.02,
            "momentum_1h": 0.005,
            "triad_strength": "BUILDING",
            "triad": {
                "inflow_quiet_load": True,
                "buy_pressure": True,
                "price_coil": True,
            },
        },
    )
    assert row is not None
    assert row["feature_schema_version"] == FEATURE_SCHEMA_VERSION
    assert isinstance(row["feature_vector"], dict)
    assert row["feature_vector"]["buy_ratio"] == 0.7
    assert row["feature_vector"]["triad_lit_count"] == 3.0
    assert row["feature_vector"]["composite_score"] == 0.61
    assert list(row["feature_keys"]) == list(FEATURE_KEYS)


def test_feature_row_prefers_frozen_over_snapshot():
    pred = {
        "feature_vector": {k: 1.0 for k in FEATURE_KEYS},
        "signal_snapshot": {"buy_ratio": 0.1, "volume_intensity": 0.1},
        "created_at": "2026-07-23T01:00:00Z",
        "pump_claim": "STIRRING",
    }
    feats = feature_row_from_prediction(pred)
    assert feats is not None
    assert feats["buy_ratio"] == 1.0


def test_train_status_and_gate(tmp_path, monkeypatch):
    pred_path = tmp_path / "predictions.json"
    matrix_path = tmp_path / "matrix.json"
    resolved = []
    for i in range(3):
        snap = {
            "buy_ratio": 0.6 + i * 0.01,
            "volume_intensity": 0.3,
            "triad": {
                "inflow_quiet_load": True,
                "buy_pressure": True,
                "price_coil": False,
            },
        }
        row = {
            "id": f"r{i}",
            "netuid": 10 + i,
            "pick_source": "pump_lead",
            "status": "resolved",
            "outcome": "hit" if i % 2 == 0 else "miss",
            "correct": i % 2 == 0,
            "sample_quality": "high",
            "created_at": "2026-07-23T10:00:00Z",
            "pump_claim": "ACCUMULATING",
            "composite_score": 0.5,
            "signal_snapshot": snap,
        }
        attach_frozen_features(row, signal_snapshot=snap, composite_score=0.5)
        resolved.append(row)
    # Rejected junk must not count
    resolved.append(
        {
            "id": "junk",
            "netuid": 0,
            "pick_source": "pump_lead",
            "status": "resolved",
            "outcome": "ungradeable",
            "correct": None,
            "sample_quality": "reject",
        }
    )
    pred_path.write_text(
        json.dumps({"predictions": [], "resolved": resolved, "stats": {}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "internal.learning.pump_lead_train.PREDICTIONS_PATH", str(pred_path)
    )

    status = dataset_status(path=str(pred_path))
    assert status["n"] == 3
    assert status["hits"] == 2
    assert status["misses"] == 1
    assert status["ready_to_train"] is False
    assert status["min_train"] == MIN_TRAIN_SAMPLES
    assert status["frozen_feature_rows"] == 3

    dry = train_offline(path=str(pred_path), dry_run=True)
    assert dry["dry_run"] is True
    assert dry["action"] == "none"

    out = train_offline(
        path=str(pred_path), matrix_path=str(matrix_path), dry_run=False
    )
    assert out["action"] == "export_only"
    assert out["reason"] == "need_more_gradeable_samples"
    assert matrix_path.exists()
    payload = json.loads(matrix_path.read_text(encoding="utf-8"))
    assert payload["n"] == 3
    assert len(payload["rows"][0]["x"]) == len(FEATURE_KEYS)

    rows = collect_training_rows(path=str(pred_path))
    assert len(rows) == 3
