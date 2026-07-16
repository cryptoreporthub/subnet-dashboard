"""§21 L8 — judge feedback into conviction confidence."""

from internal.council.conviction_bands import judge_calibration_hit_rate, judge_feedback_confidence


def test_judge_calibration_empty_without_data(monkeypatch):
    monkeypatch.setattr(
        "internal.learning.predictions_store.load_predictions",
        lambda: {"resolved": [], "predictions": []},
    )
    cal = judge_calibration_hit_rate()
    assert cal["n"] == 0
    assert cal["hit_rate"] is None


def test_judge_feedback_from_scores(monkeypatch, tmp_path):
    pred_path = tmp_path / "predictions.json"
    pred_path.write_text(
        """{
      "predictions": [{
        "id": "p1",
        "netuid": 3,
        "judge_scores_at_creation": {
          "oracle": {"confidence": 0.8},
          "echo": {"score": 0.6}
        }
      }],
      "resolved": [],
      "stats": {}
    }"""
    )
    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(pred_path))

    conf = judge_feedback_confidence({"subnet": {"netuid": 3}})
    assert conf is not None
    assert 0.6 <= conf <= 0.8
