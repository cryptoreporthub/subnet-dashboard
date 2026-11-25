"""A duplicate hour pick is re-checked in pick history with a second read.

_record_hour_pick reads pick history twice on the duplicate path: once to decide
whether to repair, and once more in the elif. If the prediction disappears between
the two reads, the pick must come back "indeterminate", not the stored kind. This
test pins that behavior so the second read is not removed as dead code.
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
def duplicate_pick(tmp_path, monkeypatch):
    path = tmp_path / "pick_history.json"
    path.write_text(json.dumps({"active": None, "history": []}))
    monkeypatch.setattr(pick_history, "PICK_HISTORY_PATH", str(path))
    monkeypatch.setattr(pick_scheduler, "_load_subnets", lambda: SUBNETS)
    monkeypatch.setattr(
        prediction_loop,
        "record_pick",
        lambda *a, **k: PickRecord(
            PickRecordKind.SKIPPED, {"id": "hour-2"}, "duplicate"
        ),
    )

    def stub_reads(answers):
        seq = iter(answers)
        monkeypatch.setattr(pick_history, "has_prediction", lambda _pid: next(seq))

    def no_write(*_a, **_k):
        raise AssertionError("duplicate path must not write a new pick")

    monkeypatch.setattr(pick_history, "record_hour_pick", no_write)
    return stub_reads


def test_duplicate_stable_in_history_returns_stored_kind(duplicate_pick):
    duplicate_pick([True, True])
    outcome = pick_scheduler._record_hour_pick(PICK, SUBNETS, {})
    assert outcome == "skipped"


def test_duplicate_vanishing_between_reads_is_indeterminate(duplicate_pick):
    duplicate_pick([True, False])
    outcome = pick_scheduler._record_hour_pick(PICK, SUBNETS, {})
    assert outcome == "indeterminate"
