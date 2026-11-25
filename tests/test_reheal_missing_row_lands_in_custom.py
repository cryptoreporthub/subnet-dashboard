"""When the custom ledger lacks today's day row, re-heal must write it there, not to the default ledger."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from internal.learning.ledger_heal import archive_predictions_epoch

def _today():
    return datetime.now(timezone.utc).date().isoformat()

def test_reheal_writes_missing_day_row_into_custom_ledger(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path); (tmp_path / "data").mkdir()
    default = tmp_path / "default" / "predictions.json"; default.parent.mkdir()
    empty = json.dumps({"predictions": [], "resolved": [], "stats": {}})
    default.write_text(empty, encoding="utf-8")
    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(default))
    daily = tmp_path / "daily_picks.json"
    pick = {"action": "long", "subnet": {"netuid": 15, "name": "SN15", "price": 1.23},
            "prediction": {"predicted_pct": 2.5, "horizon_hours": 4, "reference_price": 1.23}}
    daily.write_text(json.dumps([{"date": _today(), "action": "long", "pick": pick, "market_context": {}}]))
    monkeypatch.setattr("internal.learning.ledger_heal.DAILY_PICKS_PATH", str(daily))
    custom = tmp_path / "custom.json"; custom.write_text(empty, encoding="utf-8")
    summary = archive_predictions_epoch(reset_request_id="11111111-1111-4111-8111-111111111111", predictions_path=str(custom), archive_dir=str(tmp_path / "archive"), re_heal_daily=True)
    d = [p["netuid"] for p in json.loads(default.read_text())["predictions"]]
    c = [p["netuid"] for p in json.loads(custom.read_text())["predictions"]]
    assert (c, d) == ([15], []), f"custom={c} default={d} heal={summary.get('heal')}"
