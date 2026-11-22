"""A pick recorded while judge scoring failed gets its judge positions once scoring recovers.

The pick is ledgered and graded whether or not its positions opened at record time. This
test pins the later step: reconciliation opens the positions the judges owe for that pick.
"""

from __future__ import annotations

import json

from internal.judges import portfolios, tracker
from internal.learning import prediction_loop

PICK = {
    "subnet": {"netuid": 7, "name": "Seven"},
    "confidence": 0.7,
    "expert_contributions": {"quant": 0.6},
    "action": "long",
}
SUBNET = {"netuid": 7, "name": "Seven", "price": 12.0, "price_change_24h": 2.0}
JUDGES = ("oracle", "echo", "pulse")
RECOVERED_SCORES = {name: {"confidence": 0.6} for name in JUDGES}


def _judge_raises(*_a, **_kw):
    raise RuntimeError("judge module failed")


def _judge_recovers(*_a, **_kw):
    return dict(RECOVERED_SCORES)


def _open_position_ids(judge):
    observation = portfolios.observe_portfolios()
    if observation["kind"] == "missing":
        return []
    assert observation["kind"] == "readable", observation
    positions = observation["data"][judge].get("open_positions") or []
    return [pos.get("id") for pos in positions]


def test_pick_gets_judge_positions_when_scoring_recovers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()

    monkeypatch.setattr(tracker, "evaluate_prediction", _judge_raises)
    recorded = prediction_loop.record_pick(dict(PICK), dict(SUBNET), horizon_type="day")
    prediction_id = recorded.prediction["id"]
    assert recorded.kind is prediction_loop.PickRecordKind.INDETERMINATE
    assert recorded.reason == "positions_incomplete"
    for judge in JUDGES:
        assert _open_position_ids(judge) == [], f"{judge} has positions before reconcile"

    monkeypatch.setattr(tracker, "evaluate_prediction", _judge_recovers)
    prediction_loop.reconcile_judge_positions()

    for judge in JUDGES:
        assert _open_position_ids(judge) == [prediction_id], f"{judge} owes one position for the pick"
