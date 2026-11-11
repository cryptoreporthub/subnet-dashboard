"""Judge portfolios roll back when predictions ledger append fails."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

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
    from internal.learning.predictions_store import PersistOutcome, PersistReason, PersistResult

    with patch(
        "internal.learning.prediction_loop.append_prediction_result",
        return_value=PersistResult(PersistOutcome.FAILED, PersistReason.IO_ERROR),
    ):
        stored = prediction_loop.record_pick_prediction(pick, subnet, horizon_type="hour")

    assert stored is None
    data = json.loads(port_path.read_text(encoding="utf-8"))
    for name in ("oracle", "echo", "pulse"):
        judge = data.get(name, {})
        assert judge.get("open_positions", []) == []


def test_open_position_is_idempotent(tmp_path, monkeypatch):
    port_path = tmp_path / "judge_portfolios.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    row = {"id": "pick-1", "netuid": 7, "reference_price": 12, "horizon_hours": 1}
    portfolios.open_position("oracle", row)
    portfolios.open_position("oracle", row)
    data = json.loads(port_path.read_text())
    assert len(data["oracle"]["open_positions"]) == 1


def test_unreadable_portfolios_are_not_overwritten(tmp_path, monkeypatch):
    port_path = tmp_path / "judge_portfolios.json"
    port_path.write_text("{broken")
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    try:
        portfolios.open_position("oracle", {"id": "pick-1", "netuid": 7})
    except Exception:
        pass
    assert port_path.read_text() == "{broken"


def test_close_before_open_prevents_reopening(tmp_path, monkeypatch):
    port_path = tmp_path / "judge_portfolios.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    row = {"id": "pick-1", "netuid": 7, "reference_price": 12, "horizon_hours": 1}
    portfolios.close_position("oracle", row, actual_pct=1, outcome="hit")
    portfolios.open_position("oracle", row)
    data = json.loads(port_path.read_text())
    assert data["oracle"]["open_positions"] == []


def test_parallel_portfolio_updates_do_not_lose_a_judge(tmp_path, monkeypatch):
    port_path = tmp_path / "judge_portfolios.json"
    port_path.write_text("{}")
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    barrier = threading.Barrier(2)
    real_load = portfolios._load
    errors = []

    def synchronized_load():
        data = real_load()
        try:
            barrier.wait(timeout=1)
        except threading.BrokenBarrierError:
            pass
        return data

    def open_for(name):
        try:
            portfolios.open_position(name, {"id": "pick-1", "netuid": 7})
        except Exception as exc:
            errors.append(exc)

    monkeypatch.setattr(portfolios, "_load", synchronized_load)
    threads = [threading.Thread(target=open_for, args=(name,)) for name in ("oracle", "echo")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert not errors
    data = json.loads(port_path.read_text())
    assert len(data["oracle"]["open_positions"]) == 1
    assert len(data["echo"]["open_positions"]) == 1


def test_concurrent_open_and_close_preserve_both_changes(tmp_path, monkeypatch):
    port_path = tmp_path / "judge_portfolios.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    existing = {"id": "old", "netuid": 3, "horizon_hours": 1}
    portfolios.open_position("echo", existing)
    barrier = threading.Barrier(2)
    original = portfolios._load
    errors = []

    def read_together():
        data = original()
        try:
            barrier.wait(timeout=1)
        except threading.BrokenBarrierError:
            pass
        return data

    def run(action):
        try:
            action()
        except Exception as exc:
            errors.append(exc)

    monkeypatch.setattr(portfolios, "_load", read_together)
    threads = [
        threading.Thread(target=run, args=(lambda: portfolios.open_position("oracle", {"id": "new", "netuid": 4}),)),
        threading.Thread(target=run, args=(lambda: portfolios.close_position("echo", existing, actual_pct=1),)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert not errors
    data = json.loads(port_path.read_text())
    assert [row["id"] for row in data["oracle"]["open_positions"]] == ["new"]
    assert data["echo"]["open_positions"] == []
    assert [row["id"] for row in data["echo"]["closed_positions"]] == ["old"]


def test_evaluation_failure_does_not_commit_pick(tmp_path, monkeypatch):
    from internal.judges import echo_judge

    ledger = tmp_path / "predictions.json"
    ledger.write_text(json.dumps({"predictions": [], "resolved": [], "stats": {}}))
    before = ledger.read_bytes()
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(tmp_path / "portfolios.json"))
    monkeypatch.setattr(prediction_loop, "_link_scenario_memory", lambda *_a, **_kw: None)
    monkeypatch.setattr(echo_judge, "evaluate", lambda *_a, **_kw: (_ for _ in ()).throw(ValueError("evaluate failed")))
    pick = {"subnet": {"netuid": 7}, "confidence": 0.7, "action": "long"}
    subnet = {"netuid": 7, "name": "Seven", "price": 12.0}
    stored = prediction_loop.record_pick_prediction(pick, subnet, predictions_path=str(ledger))
    assert stored is None
    assert ledger.read_bytes() == before


def test_indeterminate_append_does_not_open_positions(tmp_path, monkeypatch):
    from internal.council import prediction_trace
    from internal.learning import predictions_store

    ledger, port_path = tmp_path / "predictions.json", tmp_path / "portfolios.json"
    ledger.write_text(json.dumps({"predictions": [], "resolved": [], "stats": {}}))
    port_path.write_text("{}")
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(prediction_loop, "_link_scenario_memory", lambda *_a, **_kw: None)
    monkeypatch.setattr(prediction_trace, "record_prediction_created", lambda *_a, **_kw: None)
    pick = {"subnet": {"netuid": 7}, "confidence": 0.7, "action": "long"}
    subnet = {"netuid": 7, "name": "Seven", "price": 12.0}
    if hasattr(prediction_loop, "record_pick"):
        monkeypatch.setattr(
            prediction_loop, "append_prediction_result",
            lambda *_a, **_kw: predictions_store.PersistResult(
                predictions_store.PersistOutcome.INDETERMINATE,
                predictions_store.PersistReason.POST_REPLACE_ERROR,
            ),
        )
        result = prediction_loop.record_pick(pick, subnet, predictions_path=str(ledger))
        assert result.kind == "indeterminate"
    else:
        monkeypatch.setattr(
            prediction_loop, "append_prediction",
            lambda *_a, **_kw: (_ for _ in ()).throw(OSError("ambiguous append")),
        )
        try:
            prediction_loop.record_pick_prediction(pick, subnet, predictions_path=str(ledger))
        except OSError:
            pass
    data = json.loads(port_path.read_text())
    assert all(not judge.get("open_positions") for judge in data.values())


def test_heal_does_not_claim_indeterminate_pick_was_healed(tmp_path, monkeypatch):
    from internal.learning import ledger_heal

    ledger = tmp_path / "predictions.json"
    ledger.write_text(json.dumps({"predictions": [], "resolved": [], "stats": {}}))
    monkeypatch.setattr(ledger_heal, "_daily_pick_today", lambda *_a: {
        "action": "LONG", "has_pick": True, "pick_netuid": 7,
    })
    monkeypatch.setattr(ledger_heal, "_day_ledger_present", lambda *_a, **_kw: False)
    monkeypatch.setattr(ledger_heal, "_today_record", lambda *_a: {
        "pick": {"subnet": {"netuid": 7}, "action": "long"},
    })
    monkeypatch.setattr(ledger_heal, "_subnet_row_for_heal", lambda *_a: {"netuid": 7, "price": 12})
    if hasattr(prediction_loop, "record_pick"):
        monkeypatch.setattr(prediction_loop, "record_pick", lambda *_a, **_kw: SimpleNamespace(
            kind="indeterminate", prediction=None, reason="post_replace_error",
        ))
    else:
        monkeypatch.setattr(prediction_loop, "record_pick_prediction", lambda *_a, **_kw: {
            "kind": "indeterminate",
        })
    result = ledger_heal.heal_daily_pick_ledger(predictions_path=str(ledger))
    assert result["ok"] is False
    assert result["healed"] is False


def test_reconcile_pending_pick_opens_missing_positions(tmp_path, monkeypatch):
    port_path, ledger = tmp_path / "portfolios.json", tmp_path / "predictions.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    ledger.write_text(json.dumps({"predictions": [{
        "id": "pick-1", "netuid": 7, "status": "pending", "pick_source": "council",
        "created_at": datetime.now(timezone.utc).isoformat(), "horizon_hours": 1,
        "judge_scores_at_creation": {
            "oracle": {"confidence": 0.5}, "echo": {"confidence": 0.5}, "pulse": {"confidence": 0.5},
        },
    }], "resolved": [], "stats": {}}))
    reconcile = getattr(prediction_loop, "reconcile_judge_positions", None)
    assert callable(reconcile)
    reconcile(predictions_path=str(ledger))
    data = json.loads(port_path.read_text())
    assert all(len(data[name]["open_positions"]) == 1 for name in ("oracle", "echo", "pulse"))


def test_reconcile_evaluates_legacy_pick_without_saved_scores(tmp_path, monkeypatch):
    from internal.judges import tracker

    port_path, ledger = tmp_path / "portfolios.json", tmp_path / "predictions.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    ledger.write_text(json.dumps({"predictions": [{
        "id": "legacy", "netuid": 7, "status": "pending", "pick_source": "council",
        "created_at": datetime.now(timezone.utc).isoformat(), "horizon_hours": 1,
    }], "resolved": [], "stats": {}}))
    monkeypatch.setattr(tracker, "evaluate_prediction", lambda *_a, **_kw: {
        name: {"confidence": 0.5} for name in ("oracle", "echo", "pulse")
    }, raising=False)
    reconcile = getattr(prediction_loop, "reconcile_judge_positions", None)
    assert callable(reconcile)
    reconcile(predictions_path=str(ledger))
    data = json.loads(port_path.read_text())
    assert all(len(data[name]["open_positions"]) == 1 for name in ("oracle", "echo", "pulse"))


def test_portfolio_save_failure_is_not_reported_as_success(tmp_path, monkeypatch):
    from internal.council import prediction_trace

    ledger, port_path = tmp_path / "predictions.json", tmp_path / "portfolios.json"
    ledger.write_text(json.dumps({"predictions": [], "resolved": [], "stats": {}}))
    port_path.write_text("{}")
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    real_save = portfolios._save
    monkeypatch.setattr(portfolios, "_save", lambda _data: (_ for _ in ()).throw(OSError("save failed")))
    monkeypatch.setattr(prediction_loop, "_link_scenario_memory", lambda *_a, **_kw: None)
    monkeypatch.setattr(prediction_trace, "record_prediction_created", lambda *_a, **_kw: None)
    monkeypatch.setattr(prediction_loop, "_append_mindmap_trail", lambda *_a, **_kw: None)
    monkeypatch.setattr(prediction_loop, "_mirror_pick_to_soul_map", lambda *_a, **_kw: None)
    pick = {"subnet": {"netuid": 7}, "confidence": 0.7, "action": "long"}
    result = prediction_loop.record_pick_prediction(
        pick, {"netuid": 7, "name": "Seven", "price": 12.0}, predictions_path=str(ledger)
    )
    assert result is None
    assert json.loads(port_path.read_text()) == {}
    monkeypatch.setattr(portfolios, "_save", real_save)
    prediction_loop.reconcile_judge_positions(predictions_path=str(ledger))
    data = json.loads(port_path.read_text())
    assert all(len(data[name]["open_positions"]) == 1 for name in ("oracle", "echo", "pulse"))


def test_hour_tick_indeterminate_pick_does_not_record_history(monkeypatch):
    from internal.council import hourly_pick, pick_history, pick_scheduler

    pick = {"action": "long", "subnet": {"netuid": 7, "price": 12}}
    monkeypatch.setattr(pick_scheduler, "_load_subnets", lambda: [{"netuid": 7, "price": 12}])
    monkeypatch.setattr(pick_scheduler, "_market_context", lambda _rows: {})
    monkeypatch.setattr(pick_scheduler, "_record_ab_benchmark", lambda *_a: None)
    monkeypatch.setattr(hourly_pick, "select_hourly_pick", lambda *_a: pick)
    monkeypatch.setattr(prediction_loop, "reconcile_judge_positions", lambda **_kw: 0, raising=False)
    history = []
    monkeypatch.setattr(pick_history, "record_hour_pick", lambda *_a, **_kw: history.append(True))
    if hasattr(prediction_loop, "record_pick"):
        monkeypatch.setattr(prediction_loop, "record_pick", lambda *_a, **_kw: SimpleNamespace(
            kind="indeterminate", prediction=None, reason="post_replace_error",
        ))
    else:
        monkeypatch.setattr(prediction_loop, "record_pick_prediction", lambda *_a, **_kw: {
            "kind": "indeterminate",
        })
    sched = pick_scheduler.HourPickScheduler(refresh_minutes=15)
    result = sched.run_once()
    assert result["ok"] is False
    assert result["pick_record_outcome"] == "indeterminate"
    assert history == []


def test_daily_pick_tick_reconciles_judge_positions(monkeypatch):
    from internal.council import daily_pick_engine, pick_scheduler

    calls = []
    monkeypatch.setattr(prediction_loop, "reconcile_judge_positions", lambda **_kw: calls.append(True), raising=False)
    monkeypatch.setattr(pick_scheduler, "_load_subnets", lambda: [])
    monkeypatch.setattr(pick_scheduler, "_market_context", lambda _rows: {})
    monkeypatch.setattr(pick_scheduler, "_record_ab_benchmark", lambda *_a: None)
    monkeypatch.setattr(pick_scheduler, "_today_pick_ready", lambda: True)
    monkeypatch.setattr(daily_pick_engine, "get_or_create_today_pick", lambda *_a, **_kw: {
        "action": "HOLD", "date": "2026-01-01",
    })
    pick_scheduler.DailyPickScheduler().run_once()
    assert calls == [True]
