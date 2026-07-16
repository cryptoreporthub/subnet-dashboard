"""§24 — pick-of-the-hour history write path."""

from internal.council import pick_history


def test_record_and_finalize_hour_pick(tmp_path, monkeypatch):
    path = tmp_path / "pick_history.json"
    monkeypatch.setattr(pick_history, "PICK_HISTORY_PATH", str(path))

    row = pick_history.record_hour_pick(
        {"confidence": 0.82, "action": "long"},
        {"netuid": 8, "name": "Taoshi", "price": 50.0},
        prediction_id="pred_hour_1",
    )
    assert row["netuid"] == 8
    assert row["entry_price"] == 50.0

    active = pick_history.get_history()["active"]
    assert active["prediction_id"] == "pred_hour_1"

    finalized = pick_history.finalize_from_prediction(
        {
            "id": "pred_hour_1",
            "horizon_type": "hour",
            "netuid": 8,
            "correct": True,
            "outcome": "hit",
            "actual_pct": 1.5,
            "resolved_price": 50.75,
        }
    )
    assert finalized["success"] is True
    stats = pick_history.get_history()["stats"]
    assert stats["wins"] == 1
    assert pick_history.get_history()["active"] is None


def test_finalize_ignores_non_hour_predictions(tmp_path, monkeypatch):
    path = tmp_path / "pick_history.json"
    monkeypatch.setattr(pick_history, "PICK_HISTORY_PATH", str(path))
    pick_history.record_hour_pick({}, {"netuid": 1, "price": 1.0}, prediction_id="p1")
    assert pick_history.finalize_from_prediction({"id": "p1", "horizon_type": "day"}) is None
    assert pick_history.get_history()["active"] is not None
