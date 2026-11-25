"""A judge evaluation fault must not drop a pick, and must not read as a clean commit."""

import json

from internal.learning.prediction_loop import PickRecordKind, record_pick


def test_pick_persists_but_is_indeterminate_when_judge_evaluation_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "internal.learning.prediction_loop.has_pending_duplicate",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "internal.judges.portfolios.PORTFOLIOS_PATH",
        str(tmp_path / "portfolios.json"),
    )

    def _judge_fault(*_a, **_k):
        raise RuntimeError("judge exploded")

    monkeypatch.setattr("internal.judges.tracker.evaluate_prediction", _judge_fault)
    monkeypatch.setattr(
        "internal.council.prediction_trace.record_prediction_created",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "internal.learning.prediction_loop._append_mindmap_trail",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "internal.learning.prediction_loop._mirror_pick_to_soul_map",
        lambda *_a, **_k: None,
    )

    pick = {
        "subnet": {"netuid": 7, "name": "X", "price": 1.0},
        "score": 80,
        "confidence": 0.6,
        "expert_contributions": {"quant": 0.5, "hype": 0.6, "dark_horse": 0.4, "technical": 0.5},
    }
    ledger = tmp_path / "predictions.json"
    result = record_pick(pick, pick["subnet"], horizon_type="hour", predictions_path=str(ledger))

    # The pick is in the ledger, but the missing judge positions must be visible to callers.
    assert result.kind is PickRecordKind.INDETERMINATE
    assert result.reason == "positions_incomplete"
    assert result.ledger_committed

    rows = json.loads(ledger.read_text())["predictions"]
    assert len(rows) == 1
    assert rows[0]["netuid"] == 7
    assert rows[0].get("judge_scores_at_creation") is None
