"""The scheduler must not report a pick as committed unless it is in pick history.

A ledger-committed prediction whose hour pick is not actually stored (a lost write,
or a lock timeout that returns quietly) must come back "indeterminate", not
"committed".
"""

from __future__ import annotations

import json

import pytest

from internal.council import pick_history, pick_scheduler
from internal.learning import prediction_loop
from internal.learning.prediction_loop import PickRecord, PickRecordKind


PICK = {"action": "long", "subnet": {"netuid": 7, "price": 12}}
SUBNETS = [{"netuid": 7, "price": 12}]


@pytest.fixture
def history_path(tmp_path, monkeypatch):
    path = tmp_path / "pick_history.json"
    path.write_text(json.dumps({"active": None, "history": []}))
    monkeypatch.setattr(pick_history, "PICK_HISTORY_PATH", str(path))
    monkeypatch.setattr(pick_scheduler, "_load_subnets", lambda: SUBNETS)
    monkeypatch.setattr(
        prediction_loop,
        "record_pick",
        lambda *a, **k: PickRecord(PickRecordKind.COMMITTED, {"id": "hour-2"}, None),
    )
    return path


def test_committed_but_unstored_pick_is_not_reported_committed(history_path, monkeypatch):
    # Simulate a write that reports a row but never reaches the file.
    monkeypatch.setattr(
        pick_history,
        "record_hour_pick",
        lambda pick, subnet, *, prediction_id=None: {"prediction_id": prediction_id},
    )
    outcome = pick_scheduler._record_hour_pick(PICK, SUBNETS, {})
    assert outcome == "indeterminate"


def test_lock_timeout_is_not_reported_committed(history_path, monkeypatch):
    def timed_out(*_a, **_kw):
        raise TimeoutError("lock busy")

    monkeypatch.setattr(pick_history, "record_hour_pick", timed_out)
    outcome = pick_scheduler._record_hour_pick(PICK, SUBNETS, {})
    assert outcome == "indeterminate"


def test_stored_pick_is_reported_committed(history_path):
    outcome = pick_scheduler._record_hour_pick(PICK, SUBNETS, {})
    assert outcome == "committed"
    assert pick_history.has_prediction("hour-2")
