"""A repaired hour-pick history row must describe the stored prediction, not the new pick.

On a duplicate hour, _record_hour_pick repairs a missing pick-history row under the
pending prediction's id. The prediction was written by the first pick of that hour.
The row written by the repair must agree with that prediction on direction, entry
price and confidence, even when the current pick says something different.
"""

from __future__ import annotations

import json

from internal.council import pick_history, pick_scheduler
from internal.learning import predictions_store
from internal.learning.prediction_loop import record_pick


OLD_SUBNET = {"netuid": 7, "price": 5.0, "name": "old"}
NEW_SUBNET = {"netuid": 7, "price": 9.99, "name": "new"}
OLD_PICK = {"netuid": 7, "action": "LONG", "direction": "up", "confidence": 0.4, "subnet": OLD_SUBNET}
NEW_PICK = {"netuid": 7, "action": "SHORT", "direction": "down", "confidence": 0.95, "subnet": NEW_SUBNET}


def test_repaired_history_row_matches_stored_prediction(tmp_path, monkeypatch):
    history_path = tmp_path / "pick_history.json"
    predictions_path = tmp_path / "predictions.json"
    monkeypatch.setattr(pick_history, "PICK_HISTORY_PATH", str(history_path))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(predictions_path))

    first = record_pick(OLD_PICK, OLD_SUBNET, horizon_type="hour")
    assert first.prediction, "the first hour pick must store a pending prediction"

    pick_scheduler._record_hour_pick(NEW_PICK, [NEW_SUBNET], {})

    stored = next(
        row for row in json.loads(predictions_path.read_text())["predictions"]
        if row.get("status") == "pending" and row.get("netuid") == 7
    )
    active = json.loads(history_path.read_text())["active"]

    assert active is not None, "the repair must write a pick-history row for the hour"
    assert active["prediction_id"] == stored["id"]
    assert active["direction"] == stored["direction"]
    assert active["entry_price"] == stored["reference_price"]
    assert active["confidence"] == stored["pick_confidence"]
