"""Judge portfolios roll back when predictions ledger append fails."""

from __future__ import annotations

import json
from unittest.mock import patch

from internal.judges import portfolios
from internal.learning import prediction_loop


def test_record_pick_prediction_discards_judge_positions_on_append_failure(
    tmp_path, monkeypatch
):
    port_path = tmp_path / "judge_portfolios.json"
    port_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))

    pick = {
        "subnet": {"netuid": 7, "name": "Seven"},
        "confidence": 0.7,
        "expert_contributions": {"quant": 0.6},
        "action": "long",
    }
    subnet = {"netuid": 7, "name": "Seven", "price": 12.0, "price_change_24h": 2.0}

    with patch(
        "internal.learning.prediction_loop.append_prediction", return_value=False
    ):
        stored = prediction_loop.record_pick_prediction(pick, subnet, horizon_type="hour")

    assert stored is None
    data = json.loads(port_path.read_text(encoding="utf-8"))
    for name in ("oracle", "echo", "pulse"):
        judge = data.get(name, {})
        assert judge.get("open_positions", []) == []
