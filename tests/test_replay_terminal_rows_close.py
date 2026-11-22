"""A resolved row in the replay stream must come back as a closed position (Gemini #1601).

The row is also on the predictions ledger, as it is in production. The live open
path skips a prediction the ledger already marks resolved, so the replay must
close it through the backfill path, not through open-then-close.
"""

import json
import os

from internal.council.replay import rebuild_judge_portfolios_from_stream


def test_resolved_row_on_ledger_rebuilds_as_closed_position(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    row = {
        "id": "r1",
        "netuid": 1,
        "name": "A",
        "direction": "up",
        "predicted_pct": 3.0,
        "reference_price": 10.0,
        "horizon_hours": 1,
        "created_at": "2026-07-01T10:00:00Z",
        "status": "resolved",
        "actual_pct": 2.0,
        "outcome": "hit",
        "correct": True,
        "resolved_price": 10.2,
    }
    os.makedirs("data")
    with open(os.path.join("data", "predictions.json"), "w", encoding="utf-8") as f:
        json.dump({"predictions": [], "resolved": [row]}, f)

    portfolios_path = tmp_path / "judge_portfolios.json"
    rebuild_judge_portfolios_from_stream([row], portfolios_path=str(portfolios_path))

    data = json.loads(portfolios_path.read_text(encoding="utf-8"))
    for judge in ("oracle", "echo", "pulse"):
        book = data.get(judge, {})
        assert book.get("open_positions", []) == []
        assert book.get("summary", {}).get("total_closed", 0) == 1
