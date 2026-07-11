"""Phase J — atomic resolution across predictions + judge portfolios."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import internal.council.resolver as resolver
import internal.judges.portfolios as portfolios
from internal.judges.tracker import on_prediction_created


@pytest.fixture(autouse=True)
def isolate_paths(tmp_path, monkeypatch):
    pred_path = str(tmp_path / "predictions.json")
    port_path = str(tmp_path / "judge_portfolios.json")
    trace_path = str(tmp_path / "trace.json")
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", pred_path)
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", port_path)
    monkeypatch.setenv("TRACE_STORE_PATH", trace_path)


def test_atomic_resolve_closes_judge_position_with_same_actual_pct():
    pred = {
        "id": "pred-ledger-1",
        "netuid": 12,
        "name": "TestNet",
        "reference_price": 50.0,
        "predicted_pct": 4.0,
        "direction": "up",
        "horizon_hours": 1,
        "expert": "quant",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    on_prediction_created(pred)
    oracle_before = portfolios.get_portfolio("oracle")
    assert oracle_before["summary"]["open_positions"] == 1

    resolved = resolver.resolve_prediction(dict(pred), current_price=52.5)
    assert resolved["actual_pct"] == 5.0
    assert resolved["correct"] is True

    oracle_after = portfolios.get_portfolio("oracle")
    assert oracle_after["summary"]["open_positions"] == 0
    assert oracle_after["summary"]["total_closed"] == 1
    closed = oracle_after["closed_positions"][0]
    assert closed["actual_pct"] == 5.0
    assert closed["pnl_pct"] > 0


def test_rebuild_portfolios_from_stream_closes_all_open():
    from internal.council.replay import rebuild_judge_portfolios_from_stream

    stream = [
        {
            "id": "a1",
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
        },
        {
            "id": "a2",
            "netuid": 2,
            "name": "B",
            "direction": "down",
            "predicted_pct": -2.0,
            "reference_price": 20.0,
            "horizon_hours": 1,
            "created_at": "2026-07-01T11:00:00Z",
            "status": "pending",
        },
    ]
    rebuild_judge_portfolios_from_stream(stream, portfolios_path=portfolios.PORTFOLIOS_PATH)
    data = json.loads(open(portfolios.PORTFOLIOS_PATH, encoding="utf-8").read())
    for judge in ("oracle", "echo", "pulse"):
        assert len(data[judge]["open_positions"]) == 1
        assert data[judge]["summary"]["total_closed"] == 1


def test_resolve_due_predictions_persists_watchdog_meta(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    data = {
        "predictions": [
            {
                "id": f"p{i}",
                "netuid": i,
                "reference_price": 100.0,
                "predicted_pct": 5.0,
                "direction": "up",
                "horizon_hours": 1,
                "resolve_at": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                "created_at": now.isoformat().replace("+00:00", "Z"),
            }
            for i in range(12)
        ],
        "resolved": [],
    }
    with open(resolver.PREDICTIONS_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh)

    result = resolver.resolve_due_predictions(subnets=[])
    assert result["watchdog"]["warning"] is True
