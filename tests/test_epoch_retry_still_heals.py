"""An epoch reset retried after a crash still re-heals today's LONG.

The first attempt clears the epoch and then crashes before the heal. The retry
must still run the heal. When the heal fails, today's LONG must be downgraded to
HOLD, because nothing else in the epoch path makes that downgrade.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from internal.learning import ledger_heal
from internal.learning.ledger_heal import archive_predictions_epoch

RESET_ID = "22222222-2222-4222-8222-222222222222"


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


def test_retry_after_crash_before_heal_still_downgrades_failed_heal(tmp_path, monkeypatch):
    custom, daily = _setup(tmp_path, monkeypatch)
    archive_dir = str(tmp_path / "archive")

    def crash(**_kw):
        raise RuntimeError("simulated process crash before heal")

    monkeypatch.setattr(ledger_heal, "heal_daily_pick_ledger", crash)
    with pytest.raises(RuntimeError):
        archive_predictions_epoch(
            reset_request_id=RESET_ID,
            predictions_path=str(custom), archive_dir=archive_dir, re_heal_daily=True,
        )

    monkeypatch.setattr(
        ledger_heal, "heal_daily_pick_ledger",
        lambda **_kw: {"ok": False, "healed": False, "reason": "record_failed"},
    )
    retry = archive_predictions_epoch(
        reset_request_id=RESET_ID,
        predictions_path=str(custom), archive_dir=archive_dir, re_heal_daily=True,
    )

    assert retry["ok"] is True
    assert retry["heal"].get("reason") == "record_failed"
    assert _today_action(daily) == "HOLD"
