"""Concurrent pick-history writers must not lose updates.

The resolver thread (finalize_from_prediction) and the hour-pick scheduler thread
(record_hour_pick) each read data/pick_history.json, change it, and write it back.
Without a shared lock, one write can overwrite the other.

Invariant checked on every iteration, true for either serial order:
  - finalize returned a row  -> the p1 history row says outcome "hit"
  - finalize returned None   -> record ran first, so p1 says outcome "replaced"
  - record_hour_pick's p2 pick is always the active row.
A lost update breaks one of these.
"""

from __future__ import annotations

import json
import threading

import internal.council.pick_history as pick_history

ITERATIONS = 50
NETUID = 7


def _seed(path):
    path.write_text(json.dumps({
        "active": {
            "netuid": NETUID, "name": "SN7", "entry_price": 1.0,
            "picked_at": "2026-01-01T00:00:00Z", "prediction_id": "p1",
            "finalized": False,
        },
        "history": [],
    }))


def test_concurrent_finalize_and_record_keep_both_updates(tmp_path, monkeypatch):
    path = tmp_path / "pick_history.json"
    monkeypatch.setattr(pick_history, "PICK_HISTORY_PATH", str(path))
    prediction = {
        "id": "p1", "horizon_type": "hour", "netuid": NETUID, "correct": True,
        "resolved_price": 1.2, "actual_pct": 20.0, "outcome": "hit",
        "resolved_at": "2026-01-01T01:00:00Z",
    }
    pick = {"netuid": NETUID, "name": "SN7", "direction": "long"}
    subnet = {"netuid": NETUID, "name": "SN7", "price": 1.5}

    failures = []
    for i in range(ITERATIONS):
        _seed(path)
        barrier = threading.Barrier(2)
        out = {}
        errors = []

        def run_finalize():
            try:
                barrier.wait()
                out["finalize"] = pick_history.finalize_from_prediction(prediction)
            except Exception as exc:  # pragma: no cover - surfaced by the assert below
                errors.append(repr(exc))

        def run_record():
            try:
                barrier.wait()
                out["record"] = pick_history.record_hour_pick(pick, subnet, prediction_id="p2")
            except Exception as exc:  # pragma: no cover
                errors.append(repr(exc))

        threads = [threading.Thread(target=run_finalize), threading.Thread(target=run_record)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        store = json.loads(path.read_text())
        p1_rows = [r for r in store["history"] if r.get("prediction_id") == "p1"]
        p1_outcome = p1_rows[0].get("outcome") if p1_rows else None
        active_id = (store.get("active") or {}).get("prediction_id")

        ok = (
            not errors
            and out.get("record") is not None
            and active_id == "p2"
            and (
                (out.get("finalize") is not None and p1_outcome == "hit")
                or (out.get("finalize") is None and p1_outcome == "replaced")
            )
        )
        if not ok:
            failures.append(
                f"iter {i}: finalize={'row' if out.get('finalize') else None} "
                f"p1_outcome={p1_outcome} active={active_id} errors={errors}"
            )

    assert failures == [], f"{len(failures)}/{ITERATIONS} iterations lost an update; first: {failures[0]}"
