"""A committed hour pick must reach pick_history even when its judge positions cannot open.

The ledger row is committed. The judge book is unreadable, so record_pick returns
INDETERMINATE with reason positions_incomplete. The scheduler path already records
pick history in that case. The server path used to drop it, because the wrapper
returned None for anything but COMMITTED.

The judge book must stay byte-identical: no silent overwrite of an unreadable book.
"""

from __future__ import annotations

import json
import os

import internal.council.pick_history as pick_history


def _subnet() -> dict:
    return {"netuid": 1, "name": "SN1", "price": 12.0, "emission": 0.5,
            "volume": 2_000_000, "action": "long"}


def test_committed_pick_with_unreadable_judge_book_reaches_pick_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DISABLE_BACKGROUND_SCANS", "1")
    os.makedirs("data", exist_ok=True)
    book = "not json {{{"
    with open(os.path.join("data", "judge_portfolios.json"), "w") as handle:
        handle.write(book)
    monkeypatch.setattr(pick_history, "PICK_HISTORY_PATH", os.path.join("data", "pick_history.json"))

    import server

    pick = {"netuid": 1, "name": "SN1", "action": "long", "direction": "long", "subnet": _subnet()}
    server._record_pick_in_learning_loop(pick, [_subnet()], {}, "hour")

    with open(os.path.join("data", "predictions.json")) as handle:
        rows = json.load(handle)["predictions"]
    assert len(rows) == 1, f"expected one committed row, got {len(rows)}"
    pid = rows[0]["id"]

    history_path = os.path.join("data", "pick_history.json")
    store = {}
    if os.path.exists(history_path):
        with open(history_path) as handle:
            store = json.load(handle)
    assert (store.get("active") or {}).get("prediction_id") == pid, "committed pick missing from pick_history"

    with open(os.path.join("data", "judge_portfolios.json")) as handle:
        assert handle.read() == book, "unreadable judge book was overwritten"
