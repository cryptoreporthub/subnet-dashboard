"""An epoch reset of a custom ledger re-heals against that ledger, not the default one."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from internal.learning.ledger_heal import archive_predictions_epoch


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def test_reheal_sees_the_day_row_kept_in_the_custom_ledger(tmp_path, monkeypatch):
    default = tmp_path / "default" / "predictions.json"
    default.parent.mkdir()
    default.write_text(json.dumps({"predictions": [], "resolved": [], "stats": {}}), encoding="utf-8")
    default_bytes = default.read_bytes()
    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(default))

    daily = tmp_path / "daily_picks.json"
    pick = {
        "action": "long",
        "subnet": {"netuid": 15, "name": "SN15", "price": 1.23},
        "prediction": {"predicted_pct": 2.5, "horizon_hours": 4, "reference_price": 1.23},
    }
    daily.write_text(json.dumps([{"date": _today(), "action": "long", "pick": pick, "market_context": {}}]))
    monkeypatch.setattr("internal.learning.ledger_heal.DAILY_PICKS_PATH", str(daily))

    day_row = {"id": "day-15", "netuid": 15, "status": "pending", "horizon_type": "day",
               "created_at": f"{_today()}T00:00:00Z"}
    custom = tmp_path / "custom.json"
    custom.write_text(json.dumps({"predictions": [day_row], "resolved": [], "stats": {}}), encoding="utf-8")

    summary = archive_predictions_epoch(
        predictions_path=str(custom), archive_dir=str(tmp_path / "archive"), re_heal_daily=True,
    )

    assert default.read_bytes() == default_bytes, "re-heal wrote into the default ledger"
    assert summary["heal"]["reason"] == "ledger_present"
    assert [p["id"] for p in json.loads(custom.read_text(encoding="utf-8"))["predictions"]] == ["day-15"]
