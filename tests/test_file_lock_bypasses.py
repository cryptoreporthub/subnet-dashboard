"""Uncoordinated writers must wait on the per-file flock, not bypass it."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

import internal.council.daily_pick_engine as daily_engine
import internal.council.resolver as resolver
import internal.learning.ledger_heal as ledger_heal


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def test_ledger_heal_respects_daily_picks_lock(tmp_path, monkeypatch):
    picks_path = tmp_path / "daily_picks.json"
    today = _today()
    picks_path.write_text(
        json.dumps([{"date": today, "action": "LONG", "pick": {"netuid": 1}}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(ledger_heal, "DAILY_PICKS_PATH", str(picks_path))

    lock_held = threading.Event()
    release_holder = threading.Event()

    def hold_lock() -> None:
        with daily_engine._locked_daily_picks(str(picks_path)):
            lock_held.set()
            assert release_holder.wait(timeout=5)

    holder = threading.Thread(target=hold_lock, name="daily-picks-lock-holder")
    holder.start()
    assert lock_held.wait(timeout=2)

    downgrade_done = threading.Event()
    box: dict = {}

    def downgrade() -> None:
        box["result"] = ledger_heal._downgrade_today_to_hold(
            reason="lock test",
            daily_picks_path=str(picks_path),
        )
        downgrade_done.set()

    worker = threading.Thread(target=downgrade, name="ledger-heal-downgrade")
    worker.start()
    assert downgrade_done.wait(timeout=0.2) is False

    release_holder.set()
    holder.join(timeout=2)
    assert downgrade_done.wait(timeout=2)
    worker.join(timeout=2)
    assert box["result"] is True

    saved = json.loads(picks_path.read_text(encoding="utf-8"))
    today_row = next(row for row in saved if row.get("date") == today)
    assert today_row["action"] == "HOLD"
    assert today_row["pick"] is None


def test_resolver_save_respects_predictions_lock(tmp_path, monkeypatch):
    pred_path = tmp_path / "predictions.json"
    lock_path = tmp_path / "predictions.json.lock"
    pred_path.write_text(
        json.dumps(
            {
                "predictions": [],
                "resolved": [],
                "stats": {
                    "correct": 0,
                    "wrong": 0,
                    "pending": 0,
                    "total": 0,
                    "accuracy": 0.0,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "internal.learning.predictions_store.PREDICTIONS_PATH", str(pred_path)
    )
    monkeypatch.setattr(
        "internal.learning.predictions_store.PREDICTIONS_LOCK_PATH", str(lock_path)
    )
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(pred_path))

    lock_held = threading.Event()
    release_holder = threading.Event()

    def hold_lock() -> None:
        from internal.learning.predictions_store import locked_predictions_file

        with locked_predictions_file():
            lock_held.set()
            assert release_holder.wait(timeout=5)

    holder = threading.Thread(target=hold_lock, name="predictions-lock-holder")
    holder.start()
    assert lock_held.wait(timeout=2)

    save_done = threading.Event()

    def save() -> None:
        resolver._save_json(
            str(pred_path),
            {
                "predictions": [{"id": "pred_lock_test", "netuid": 1}],
                "resolved": [],
                "stats": {
                    "correct": 0,
                    "wrong": 0,
                    "pending": 1,
                    "total": 1,
                    "accuracy": 0.0,
                },
            },
            caller="test",
        )
        save_done.set()

    worker = threading.Thread(target=save, name="resolver-save")
    worker.start()
    assert save_done.wait(timeout=0.2) is False

    release_holder.set()
    holder.join(timeout=2)
    assert save_done.wait(timeout=2)
    worker.join(timeout=2)

    saved = json.loads(pred_path.read_text(encoding="utf-8"))
    assert saved["predictions"][0]["id"] == "pred_lock_test"
