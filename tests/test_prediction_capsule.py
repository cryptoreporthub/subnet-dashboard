"""§21 L12 — prediction time-capsule replay."""

from internal.learning.prediction_capsule import build_share_card, get_prediction_capsule


def test_capsule_not_found():
    out = get_prediction_capsule("nonexistent-id-xyz")
    assert out["status"] == "not_found"


def test_capsule_and_share_card(tmp_path, monkeypatch):
    pred_path = tmp_path / "predictions.json"
    pred_path.write_text(
        """{
      "predictions": [],
      "resolved": [{
        "id": "pred_capsule_1",
        "netuid": 8,
        "name": "Taoshi",
        "statement": "Token up on delegation flow",
        "predicted_pct": 3.5,
        "actual_pct": 2.1,
        "correct": true,
        "outcome": "hit",
        "subnet_snapshot": {
          "staking_yield_apy": 12.0,
          "price_change_7d": -4.0,
          "yield_trap": true
        },
        "judge_scores_at_creation": {
          "oracle": {"confidence": 0.72},
          "echo": {"score": 0.65}
        }
      }],
      "stats": {}
    }"""
    )
    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(pred_path))

    out = get_prediction_capsule("pred_capsule_1")
    assert out["status"] == "success"
    assert out["capsule"]["subnet_snapshot"]["yield_trap"] is True
    share = build_share_card(out["prediction"])
    assert "Taoshi" in share
    assert "yield trap" in share.lower() or "Yield trap" in share
