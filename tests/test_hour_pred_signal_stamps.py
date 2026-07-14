"""Hourly prediction + learning signal stamps + HOLD candidate call text."""

from __future__ import annotations

import json

from internal.council.daily_pick import select_daily_pick
from internal.council.hourly_pick import select_hourly_pick
from internal.council.state_vector import unpack_score_learning_fields
from internal.learning.prediction_loop import record_pick_prediction


def _sn(**overrides):
    base = {
        "netuid": 19,
        "name": "Inference",
        "symbol": "INF",
        "price": 12.0,
        "volume": 8_000,
        "market_cap": 500_000,
        "emission": 4.0,
        "apy": 40.0,
        "price_change_24h": 8.0,
        "price_change_7d": 12.0,
        "status": "active",
    }
    base.update(overrides)
    return base


def test_hourly_pick_attaches_prediction_and_learning_stamps():
    pick = select_hourly_pick([_sn()])
    assert pick["prediction"] is not None
    assert pick["prediction"]["statement"]
    assert pick["prediction"]["horizon_hours"] == 1
    assert pick["prediction"]["horizon_type"] == "hour"
    assert "signal_impact" in pick
    # Nested tech stamps also lifted to pick root when score provides them.
    learning = unpack_score_learning_fields(
        {
            "expert_contributions": pick["expert_contributions"],
            "signal_impact": pick.get("signal_impact"),
        }
    )
    assert learning["signal_impact"] is not None or pick.get("signal_impact") is not None


def test_daily_pick_exposes_signal_stamps_on_root():
    pick = select_daily_pick([_sn()])
    assert pick["prediction"] is not None
    assert pick.get("signal_impact") is not None or pick["prediction"].get("signal_contributions") is not None
    # Prediction should carry tech stamps when present on score.
    pred = pick["prediction"]
    assert pred.get("signal_contributions") is None or isinstance(pred["signal_contributions"], dict)
    if pick.get("active_signals"):
        assert pred.get("active_signals") == pick["active_signals"]


def test_record_preserves_existing_prediction_and_stamps(tmp_path, monkeypatch):
    pred_path = str(tmp_path / "predictions.json")
    monkeypatch.setattr("internal.council.resolver.PREDICTIONS_PATH", pred_path)
    monkeypatch.setattr(
        "internal.learning.predictions_store.PREDICTIONS_PATH",
        pred_path,
    )
    with open(pred_path, "w") as f:
        json.dump({"predictions": [], "resolved": []}, f)

    # Avoid soul_map / mindmap side effects writing into repo data/
    monkeypatch.setattr(
        "internal.learning.prediction_loop._append_mindmap_trail",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "internal.learning.prediction_loop._mirror_pick_to_soul_map",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "internal.learning.prediction_loop._link_scenario_memory",
        lambda *a, **k: None,
    )

    pick = select_hourly_pick([_sn(price=5.0)])
    assert pick["prediction"]
    statement = pick["prediction"]["statement"]
    recorded = record_pick_prediction(
        pick,
        subnet=_sn(price=5.0),
        market_context={},
        horizon_type="hour",
    )
    assert recorded is not None
    assert recorded.get("statement") == statement
    assert recorded.get("horizon_hours") == 1
    # signal_impact (not metric-only signals) used for judges path — at least stamped on pick
    assert pick.get("signal_impact") is not None or recorded.get("signal_contributions") is not None


def test_unpack_score_learning_fields_nested():
    fields = unpack_score_learning_fields(
        {
            "expert_contributions": {
                "quant": 0.6,
                "hype": 0.5,
                "dark_horse": 0.4,
                "technical": 0.55,
                "signal_contributions": {"rsi": {"score": 0.7}},
                "active_signals": ["rsi"],
                "technical_score": 0.6,
            },
            "signal_impact": {"net_predicted_pct": 1.5, "impacts": []},
        }
    )
    assert fields["experts"]["quant"] == 0.6
    assert fields["signal_contributions"] == {"rsi": {"score": 0.7}}
    assert fields["active_signals"] == ["rsi"]
    assert fields["signal_impact"]["net_predicted_pct"] == 1.5
