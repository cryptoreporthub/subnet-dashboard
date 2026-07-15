"""N1 council hardening — subnet_snapshot + judge score persistence."""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import patch

from internal.council.grading import hybrid_score
from internal.learning.predictions_store import load_predictions, sync_pending_prediction
from internal.learning.prediction_loop import _subnet_snapshot, record_pick_prediction


def test_subnet_snapshot_extracts_fields():
    snap = _subnet_snapshot(
        {
            "price_change_24h": -1.2,
            "volume": 500.0,
            "emission": 0.08,
            "price": 1.5,
            "social_mentions": 42,
            "staking_data": {"apy": 0.25},
        }
    )
    assert snap["apy"] == 0.25
    assert snap["volume"] == 500.0
    assert snap["emission"] == 0.08


def test_hybrid_score_deferred_returns_none():
    assert hybrid_score({"direction": "up"}, 3.0) is None


def test_sync_pending_prediction_merges_fields():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "predictions.json")
        data = {
            "predictions": [{"id": "abc123", "netuid": 1, "status": "pending"}],
            "resolved": [],
            "stats": {},
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        with patch("internal.learning.predictions_store.PREDICTIONS_PATH", path):
            ok = sync_pending_prediction(
                "abc123",
                {"judge_scores_at_creation": {"oracle": {"score": 0.6}}},
            )
            assert ok is True
            loaded = load_predictions()
            row = loaded["predictions"][0]
            assert row["judge_scores_at_creation"]["oracle"]["score"] == 0.6


def test_record_pick_stores_subnet_snapshot(tmp_path, monkeypatch):
    pred_path = tmp_path / "predictions.json"
    pred_path.write_text(
        json.dumps({"predictions": [], "resolved": [], "stats": {}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "internal.learning.predictions_store.PREDICTIONS_PATH",
        str(pred_path),
    )
    monkeypatch.setattr(
        "internal.judges.tracker.on_prediction_created",
        lambda *a, **k: {"oracle": {"score": 0.55}},
    )
    monkeypatch.setattr(
        "internal.learning.prediction_loop._link_scenario_memory",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "internal.learning.prediction_loop._append_mindmap_trail",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "internal.learning.prediction_loop._mirror_pick_to_soul_map",
        lambda *a, **k: None,
    )

    pick = {
        "netuid": 7,
        "name": "TestNet",
        "score": 0.8,
        "confidence": 0.7,
        "expert_contributions": {"quant": 0.9},
    }
    subnet = {
        "netuid": 7,
        "name": "TestNet",
        "price": 2.0,
        "volume": 100.0,
        "price_change_24h": 0.5,
        "emission": 0.1,
    }
    pred = record_pick_prediction(pick, subnet, horizon_type="hour")
    assert pred is not None
    loaded = json.loads(pred_path.read_text(encoding="utf-8"))
    row = loaded["predictions"][0]
    assert row["subnet_snapshot"]["volume"] == 100.0
    assert row["judge_scores_at_creation"]["oracle"]["score"] == 0.55
