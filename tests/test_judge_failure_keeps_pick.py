"""A pick whose judge scoring raises still lands in the predictions ledger.

The daily pick is already saved, so dropping the ledger row means it is never graded.
"""

from __future__ import annotations

import json

from internal.judges import tracker
from internal.learning import prediction_loop

PICK = {
    "subnet": {"netuid": 7, "name": "Seven"},
    "confidence": 0.7,
    "expert_contributions": {"quant": 0.6},
    "action": "long",
}
SUBNET = {"netuid": 7, "name": "Seven", "price": 12.0, "price_change_24h": 2.0}


def _ledger_rows(path):
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["predictions"] if isinstance(data, dict) else data


def _judge_raises(*_a, **_kw):
    raise RuntimeError("judge module failed")


def test_pick_is_ledgered_when_judge_scoring_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(tracker, "evaluate_prediction", _judge_raises)

    prediction_loop.record_pick_prediction(dict(PICK), dict(SUBNET), horizon_type="day")

    rows = _ledger_rows(tmp_path / "data" / "predictions.json")
    assert [r.get("netuid") for r in rows] == [7]


def test_control_pick_is_ledgered_when_judge_scoring_works(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()

    prediction_loop.record_pick_prediction(dict(PICK), dict(SUBNET), horizon_type="day")

    rows = _ledger_rows(tmp_path / "data" / "predictions.json")
    assert [r.get("netuid") for r in rows] == [7]
