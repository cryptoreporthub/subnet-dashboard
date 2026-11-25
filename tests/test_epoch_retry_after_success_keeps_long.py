"""A repeated epoch reset after a successful heal keeps today's LONG.

The first attempt runs the real heal and succeeds. The same reset id then
arrives again. The retry runs the real heal again on the healed day, so today's
LONG must still be LONG and must not be downgraded.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from internal.learning import ledger_heal
from internal.learning.ledger_heal import archive_predictions_epoch

RESET_ID = "33333333-3333-4333-8333-333333333333"


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _setup(tmp_path, monkeypatch):
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

    custom = tmp_path / "custom.json"
    custom.write_text(json.dumps({"predictions": [], "resolved": [], "stats": {}}), encoding="utf-8")
    return custom, daily


def _today_action(daily) -> str:
    return next(row["action"] for row in json.loads(daily.read_text()) if row["date"] == _today()).upper()


def test_repeated_reset_after_successful_heal_keeps_long(tmp_path, monkeypatch):
    custom, daily = _setup(tmp_path, monkeypatch)
    archive_dir = str(tmp_path / "archive")
    calls = []
    real_heal = ledger_heal.heal_daily_pick_ledger

    def recording_heal(**kw):
        result = real_heal(**kw)
        calls.append(result)
        return result

    monkeypatch.setattr(ledger_heal, "heal_daily_pick_ledger", recording_heal)
    first = archive_predictions_epoch(
        reset_request_id=RESET_ID, predictions_path=str(custom), archive_dir=archive_dir, re_heal_daily=True,
    )
    assert first["heal"].get("healed") is True, first["heal"]
    assert _today_action(daily) == "LONG"

    second = archive_predictions_epoch(
        reset_request_id=RESET_ID, predictions_path=str(custom), archive_dir=archive_dir, re_heal_daily=True,
    )
    print("SECOND HEAL RESULT:", calls[-1])
    print("SECOND DOWNGRADE FLAG:", second["heal"].get("downgraded_daily_pick"))

    assert _today_action(daily) == "LONG"
