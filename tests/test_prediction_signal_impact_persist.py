"""signal_impact must persist on prediction rows."""

from internal.learning.prediction_loop import record_pick_prediction


def test_record_pick_prediction_persists_signal_impact(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "internal.learning.prediction_loop.has_pending_duplicate",
        lambda *_a, **_k: False,
    )
    monkeypatch.setattr(
        "internal.learning.prediction_loop.append_prediction",
        lambda pred: pred,
    )
    monkeypatch.setattr(
        "internal.judges.tracker.on_prediction_created",
        lambda *_a, **_k: {"oracle": {"score": 0.5, "confidence": 0.5}},
    )
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

    si = {"impacts": [{"direction": "bullish"}], "net_direction": "bullish"}
    pick = {
        "subnet": {"netuid": 7, "name": "X", "price": 1.0},
        "score": 80,
        "confidence": 0.6,
        "signal_impact": si,
        "expert_contributions": {"quant": 0.5, "hype": 0.6, "dark_horse": 0.4, "technical": 0.5},
    }
    pred = record_pick_prediction(pick, pick["subnet"], horizon_type="hour")
    assert isinstance(pred.get("signal_impact"), dict)
    assert pred["signal_impact"]["net_direction"] == "bullish"
