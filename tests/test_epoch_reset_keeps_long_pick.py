"""An epoch reset keeps today's LONG pick when its row is already in the ledger.

Downgrading to HOLD is for a heal that really failed, not for a heal that
found the row already present.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from internal.learning import ledger_heal
from internal.learning.ledger_heal import archive_predictions_epoch

RESET_ID = "11111111-1111-4111-8111-111111111111"


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _setup(tmp_path, monkeypatch, *, with_day_row: bool):
    default = tmp_path / "default" / "predictions.json"
    default.parent.mkdir()
    default.write_text(json.dumps({"predictions": [], "resolved": [], "stats": {}}), encoding="utf-8")
    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(default))

    daily = tmp_path / "daily_picks.json"
    pick = {
        "action": "long",
        "subnet": {"netuid": 15, "name": "SN15", "price": 1.23},
        "prediction": {"predicted_pct": 2.5, "horizon_hours": 4, "reference_price": 1.23},
    }
    daily.write_text(json.dumps([{"date": _today(), "action": "long", "pick": pick, "market_context": {}}]))
    monkeypatch.setattr("internal.learning.ledger_heal.DAILY_PICKS_PATH", str(daily))

    rows = []
    if with_day_row:
        rows.append({"id": "day-15", "netuid": 15, "status": "pending", "horizon_type": "day",
                     "created_at": f"{_today()}T00:00:00Z"})
    custom = tmp_path / "custom.json"
    custom.write_text(json.dumps({"predictions": rows, "resolved": [], "stats": {}}), encoding="utf-8")
    return custom, daily


def _today_action(daily) -> str:
    return next(row["action"] for row in json.loads(daily.read_text()) if row["date"] == _today()).upper()


def test_row_already_present_keeps_the_long_pick(tmp_path, monkeypatch):
    custom, daily = _setup(tmp_path, monkeypatch, with_day_row=True)

    summary = archive_predictions_epoch(
        reset_request_id=RESET_ID,
        predictions_path=str(custom), archive_dir=str(tmp_path / "archive"), re_heal_daily=True,
    )

    assert summary["heal"]["reason"] == "ledger_present"
    assert _today_action(daily) == "LONG"


def test_failed_heal_still_downgrades_to_hold(tmp_path, monkeypatch):
    custom, daily = _setup(tmp_path, monkeypatch, with_day_row=False)
    monkeypatch.setattr(
        ledger_heal, "heal_daily_pick_ledger",
        lambda **_kw: {"ok": False, "healed": False, "reason": "record_failed"},
    )

    archive_predictions_epoch(
        reset_request_id=RESET_ID,
        predictions_path=str(custom), archive_dir=str(tmp_path / "archive"), re_heal_daily=True,
    )

    assert _today_action(daily) == "HOLD"


def test_row_written_by_another_writer_keeps_the_long_pick(tmp_path, monkeypatch):
    """The write loses a race: another writer adds today's row first, so the heal reports duplicate_skipped."""
    from internal.learning import prediction_loop

    custom, daily = _setup(tmp_path, monkeypatch, with_day_row=False)
    skipped = prediction_loop.PickRecord(prediction_loop.PickRecordKind.SKIPPED, reason="duplicate")
    monkeypatch.setattr(prediction_loop, "record_pick_prediction", lambda *_a, **_kw: None, raising=False)
    monkeypatch.setattr(prediction_loop, "record_pick", lambda *_a, **_kw: skipped, raising=False)
    checks = []

    def _present(_netuid, *_args, **_kwargs):
        checks.append(1)
        return len(checks) > 1  # absent on the pre-check, present after the failed write

    monkeypatch.setattr(ledger_heal, "_day_ledger_present", _present)

    summary = archive_predictions_epoch(
        reset_request_id=RESET_ID,
        predictions_path=str(custom), archive_dir=str(tmp_path / "archive"), re_heal_daily=True,
    )

    assert summary["heal"]["reason"] == "duplicate_skipped"
    assert _today_action(daily) == "LONG"


def test_long_without_a_pick_payload_downgrades_to_hold(tmp_path, monkeypatch):
    """A LONG with no usable pick cannot be graded, so it must not stay LONG."""
    custom, daily = _setup(tmp_path, monkeypatch, with_day_row=False)
    rows = json.loads(daily.read_text())
    for row in rows:
        row["pick"] = {}
    daily.write_text(json.dumps(rows))

    summary = archive_predictions_epoch(
        reset_request_id=RESET_ID,
        predictions_path=str(custom), archive_dir=str(tmp_path / "archive"), re_heal_daily=True,
    )

    assert summary["heal"]["reason"] == "no_published_long"
    assert _today_action(daily) == "HOLD"
