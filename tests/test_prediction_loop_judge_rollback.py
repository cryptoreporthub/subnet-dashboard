"""Judge portfolios roll back when predictions ledger append fails."""

from __future__ import annotations

import json
import time
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
    """A real close (open then close) blocks a later open; close-without-open does not invent PnL."""
    from internal.learning import predictions_store

    port_path = tmp_path / "judge_portfolios.json"
    ledger = tmp_path / "predictions.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(ledger))
    row = {"id": "pick-1", "netuid": 7, "reference_price": 12, "horizon_hours": 1}
    # Close-without-open must not invent a closed row or a tombstone.
    assert portfolios.close_position("oracle", row, actual_pct=1, outcome="hit") is None
    opened = portfolios.open_position("oracle", row)
    assert opened is not None
    # After a real close, a late open is refused.
    assert portfolios.close_position("oracle", row, actual_pct=1, outcome="hit") is not None
    assert portfolios.open_position("oracle", row) is None
    data = json.loads(port_path.read_text())
    assert data["oracle"]["open_positions"] == []
    assert len(data["oracle"]["closed_positions"]) == 1

    terminal = {
        "id": "pick-term",
        "netuid": 7,
        "status": "resolved",
        "outcome": "hit",
        "correct": True,
    }
    ledger.write_text(json.dumps({"predictions": [], "resolved": [terminal], "stats": {}}))
    assert portfolios.open_position("oracle", terminal) is None


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
    """Both changes persist when open and close run at the same time.

    A barrier inside `_load_checked` would deadlock: each writer holds the
    portfolios lock while waiting for the other. This test runs both writers
    concurrently and requires both results, with a join timeout so a
    deadlock fails the suite.
    """
    port_path = tmp_path / "judge_portfolios.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    existing = {"id": "old", "netuid": 3, "horizon_hours": 1}
    portfolios.open_position("echo", existing)
    errors = []

    def run(action):
        try:
            action()
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=run, args=(lambda: portfolios.open_position("oracle", {"id": "new", "netuid": 4}),)),
        threading.Thread(target=run, args=(lambda: portfolios.close_position("echo", existing, actual_pct=1),)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive(), "portfolio writer deadlocked"
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



def _gradeable_row(pred_id="partial-1", *, outcome="miss", actual_pct=-3.0, include_correct=True):
    row = {
        "id": pred_id,
        "netuid": 7,
        "name": "Seven",
        "direction": "up",
        "predicted_pct": 5.0,
        "reference_price": 100.0,
        "horizon_hours": 1,
        "outcome": outcome,
        "actual_pct": actual_pct,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "status": "resolved",
    }
    if include_correct:
        row["correct"] = outcome == "hit"
    return row


def _open_all_judges(row):
    for name in ("oracle", "echo", "pulse"):
        portfolios.open_position(name, row)


def test_reconcile_completes_partial_judge_close(tmp_path, monkeypatch):
    """T3: after the second judge close raises, reconcile finishes all three once."""
    from internal.judges import postmortems, tracker

    port_path = tmp_path / "portfolios.json"
    ledger = tmp_path / "predictions.json"
    pm_dir = tmp_path / "postmortems"
    pm_dir.mkdir()
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(pm_dir))
    row = _gradeable_row()
    _open_all_judges(row)
    ledger.write_text(json.dumps({"predictions": [], "resolved": [row], "stats": {}}))

    real_close = portfolios.close_position
    state = {"echo_calls": 0}

    def close_echo_fails(judge_name, prediction, *args, **kwargs):
        if judge_name == "echo":
            state["echo_calls"] += 1
            if state["echo_calls"] == 1:
                raise OSError("echo close failed")
        return real_close(judge_name, prediction, *args, **kwargs)

    monkeypatch.setattr(portfolios, "close_position", close_echo_fails)
    try:
        tracker.on_prediction_resolved(row, apply_judge_nudge=False)
    except OSError:
        pass

    data = json.loads(port_path.read_text())
    assert len(data["oracle"]["closed_positions"]) == 1
    assert data["echo"]["open_positions"]
    closed = prediction_loop.reconcile_judge_positions(predictions_path=str(ledger))
    assert closed >= 1
    data = json.loads(port_path.read_text())
    assert all(len(data[name]["open_positions"]) == 0 for name in ("oracle", "echo", "pulse"))
    assert len(data["oracle"]["closed_positions"]) == 1
    assert len(data["echo"]["closed_positions"]) == 1
    assert len(data["pulse"]["closed_positions"]) == 1
    if (pm_dir / "oracle.json").exists():
        oracle_pm = json.loads((pm_dir / "oracle.json").read_text())
        assert len(oracle_pm) == 1

    # T10: second pass is a no-op
    prediction_loop.reconcile_judge_positions(predictions_path=str(ledger))
    data = json.loads(port_path.read_text())
    assert len(data["oracle"]["closed_positions"]) == 1
    if (pm_dir / "oracle.json").exists():
        oracle_pm = json.loads((pm_dir / "oracle.json").read_text())
        assert len(oracle_pm) == 1


def test_reconcile_does_not_close_ungradeable_open_position(tmp_path, monkeypatch):
    """T9 GUARD: an ungradeable resolved row with an open position stays open."""
    from internal.judges import postmortems

    port_path = tmp_path / "portfolios.json"
    ledger = tmp_path / "predictions.json"
    pm_dir = tmp_path / "postmortems"
    pm_dir.mkdir()
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(pm_dir))
    row = _gradeable_row(pred_id="ungrade-1", outcome="ungradeable", actual_pct=None, include_correct=True)
    row["correct"] = None
    _open_all_judges(row)
    before = json.loads(port_path.read_text())
    loss_before = before["oracle"]["summary"]["loss_count"]
    ledger.write_text(json.dumps({"predictions": [], "resolved": [row], "stats": {}}))
    prediction_loop.reconcile_judge_positions(predictions_path=str(ledger))
    data = json.loads(port_path.read_text())
    assert all(len(data[name]["open_positions"]) == 1 for name in ("oracle", "echo", "pulse"))
    assert data["oracle"]["closed_positions"] == []
    assert data["oracle"]["summary"]["loss_count"] == loss_before
    assert not (pm_dir / "oracle.json").exists()


def test_reconcile_closes_legacy_row_without_stored_correct(tmp_path, monkeypatch):
    """T9b: a legacy hit with actual_pct and no correct key is closed."""
    from internal.judges import postmortems

    port_path = tmp_path / "portfolios.json"
    ledger = tmp_path / "predictions.json"
    pm_dir = tmp_path / "postmortems"
    pm_dir.mkdir()
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(pm_dir))
    row = _gradeable_row(pred_id="legacy-hit", outcome="hit", actual_pct=4.0, include_correct=False)
    assert "correct" not in row
    _open_all_judges(row)
    ledger.write_text(json.dumps({"predictions": [], "resolved": [row], "stats": {}}))
    prediction_loop.reconcile_judge_positions(predictions_path=str(ledger))
    data = json.loads(port_path.read_text())
    assert all(len(data[name]["open_positions"]) == 0 for name in ("oracle", "echo", "pulse"))
    assert all(len(data[name]["closed_positions"]) == 1 for name in ("oracle", "echo", "pulse"))


def test_hour_tick_records_pick_when_reconcile_times_out(monkeypatch):
    """T12: a portfolios lock timeout must not drop the hour's pick."""
    from internal.council import hourly_pick, pick_scheduler

    def boom(**_kw):
        raise portfolios.PortfolioLockTimeout("portfolios lock held")

    monkeypatch.setattr(prediction_loop, "reconcile_judge_positions", boom, raising=False)
    monkeypatch.setattr(pick_scheduler, "_load_subnets", lambda: [{"netuid": 7, "price": 12}])
    monkeypatch.setattr(pick_scheduler, "_market_context", lambda _rows: {})
    monkeypatch.setattr(pick_scheduler, "_record_ab_benchmark", lambda *_a: None)
    monkeypatch.setattr(hourly_pick, "select_hourly_pick", lambda *_a: {"action": "long", "subnet": {"netuid": 7, "price": 12}})
    monkeypatch.setattr(pick_scheduler, "_record_hour_pick", lambda *_a, **_kw: "applied")
    result = pick_scheduler.HourPickScheduler(refresh_minutes=15).run_once()
    assert result["ok"] is True
    assert result.get("reconcile_ok") is False
    assert "reconcile_error" in result
    assert result.get("pick_record_outcome") == "applied"


def test_daily_tick_still_picks_when_reconcile_times_out(monkeypatch):
    """T12: a portfolios lock timeout must not write a daily scheduler_hold."""
    from internal.council import daily_pick_engine, pick_scheduler

    def boom(**_kw):
        raise portfolios.PortfolioLockTimeout("portfolios lock held")

    monkeypatch.setattr(prediction_loop, "reconcile_judge_positions", boom, raising=False)
    monkeypatch.setattr(pick_scheduler, "_load_subnets", lambda: [])
    monkeypatch.setattr(pick_scheduler, "_market_context", lambda _rows: {})
    monkeypatch.setattr(pick_scheduler, "_record_ab_benchmark", lambda *_a: None)
    monkeypatch.setattr(pick_scheduler, "_today_pick_ready", lambda: True)
    monkeypatch.setattr(daily_pick_engine, "get_or_create_today_pick", lambda *_a, **_kw: {
        "action": "HOLD", "date": "2026-01-01",
    })
    result = pick_scheduler.DailyPickScheduler().run_once()
    assert result["ok"] is True
    assert result.get("reconcile_ok") is False
    assert not result.get("scheduler_hold")


def test_postmortem_retries_after_durable_close(tmp_path, monkeypatch):
    """A postmortem write failure after a durable close is retried; no duplicate."""
    from internal.judges import postmortems, tracker

    port_path = tmp_path / "judge_portfolios.json"
    pm_dir = tmp_path / "postmortems"
    pm_dir.mkdir()
    pred_path = tmp_path / "predictions.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(pm_dir))
    row = _gradeable_row(pred_id="pm-1", outcome="miss", actual_pct=-3.0)
    pred_path.write_text(json.dumps({"predictions": [], "resolved": [row], "stats": {}}))
    from internal.learning import predictions_store
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred_path))
    # Seed held closed positions via the rebuild backfill path. A post-resolve
    # open would be refused by the terminal-ledger open rule.
    for name in ("oracle", "echo", "pulse"):
        portfolios.backfill_closed_position(name, row, actual_pct=-3.0, outcome="miss")

    real = postmortems.record
    calls = {"oracle": 0}

    def flaky(judge_name, prediction, actual_pct=None):
        if judge_name == "oracle" and calls["oracle"] == 0:
            calls["oracle"] += 1
            raise OSError("postmortem write failed")
        if judge_name == "oracle":
            calls["oracle"] += 1
        return real(judge_name, prediction, actual_pct)

    monkeypatch.setattr(postmortems, "record", flaky)
    tracker.on_prediction_resolved(row, apply_judge_nudge=False)
    first = {name: len(postmortems.list_for_judge(name)) for name in ("oracle", "echo", "pulse")}
    assert first["oracle"] == 0
    assert first["echo"] == 1
    assert first["pulse"] == 1
    data = json.loads(port_path.read_text())
    assert all(len(data[name]["open_positions"]) == 0 for name in ("oracle", "echo", "pulse"))

    prediction_loop.reconcile_judge_positions(predictions_path=str(pred_path))
    second = {name: len(postmortems.list_for_judge(name)) for name in ("oracle", "echo", "pulse")}
    assert second == {"oracle": 1, "echo": 1, "pulse": 1}
    prediction_loop.reconcile_judge_positions(predictions_path=str(pred_path))
    third = {name: len(postmortems.list_for_judge(name)) for name in ("oracle", "echo", "pulse")}
    assert third == {"oracle": 1, "echo": 1, "pulse": 1}


def test_hit_with_null_correct_is_not_a_wrong_pick(tmp_path, monkeypatch):
    """A gradeable hit with correct: null must not write wrong-pick postmortems."""
    from internal.judges import postmortems, tracker

    port_path = tmp_path / "judge_portfolios.json"
    pm_dir = tmp_path / "postmortems"
    pm_dir.mkdir()
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(pm_dir))
    row = _gradeable_row(pred_id="null-correct", outcome="hit", actual_pct=4.0, include_correct=False)
    row["correct"] = None
    _open_all_judges(row)
    tracker.on_prediction_resolved(row, apply_judge_nudge=False)
    assert all(len(postmortems.list_for_judge(name)) == 0 for name in ("oracle", "echo", "pulse"))
    data = json.loads(port_path.read_text())
    assert all(len(data[name]["open_positions"]) == 0 for name in ("oracle", "echo", "pulse"))


def test_hour_history_written_when_portfolio_open_is_incomplete(tmp_path, monkeypatch):
    """Ledger-committed but positions_incomplete still records hour history once."""
    from internal.council import pick_history, pick_scheduler
    from internal.learning.prediction_loop import PickRecord, PickRecordKind

    hist_path = tmp_path / "hour_history.json"
    monkeypatch.setattr(pick_history, "PICK_HISTORY_PATH", str(hist_path))

    history_ids = []
    real_record = pick_history.record_hour_pick

    def tracking(pick, subnet, *, prediction_id=None):
        history_ids.append(prediction_id)
        return real_record(pick, subnet, prediction_id=prediction_id)

    monkeypatch.setattr(pick_history, "record_hour_pick", tracking)
    stored = PickRecord(
        PickRecordKind.INDETERMINATE,
        {"id": "hour-1"},
        "positions_incomplete",
    )
    monkeypatch.setattr(prediction_loop, "record_pick", lambda *a, **k: stored)
    monkeypatch.setattr(pick_scheduler, "_load_subnets", lambda: [{"netuid": 7, "price": 12}])
    outcome = pick_scheduler._record_hour_pick(
        {"action": "long", "subnet": {"netuid": 7, "price": 12}},
        [{"netuid": 7, "price": 12}],
        {},
    )
    assert outcome == "indeterminate"
    assert history_ids == ["hour-1"]
    # Retry with the same prediction id must not append a second history row.
    outcome2 = pick_scheduler._record_hour_pick(
        {"action": "long", "subnet": {"netuid": 7, "price": 12}},
        [{"netuid": 7, "price": 12}],
        {},
    )
    assert outcome2 == "indeterminate"
    assert history_ids == ["hour-1", "hour-1"]
    store = pick_history._load()
    assert store.get("active", {}).get("prediction_id") == "hour-1"
    history = store.get("history") or []
    assert all(row.get("prediction_id") != "hour-1" or row.get("outcome") != "replaced" for row in history) or len(history) == 0
    # Stronger: only one live/active entry, no retired copy of hour-1.
    retired_same = [row for row in history if row.get("prediction_id") == "hour-1"]
    assert retired_same == []


def test_nudge_io_does_not_consume_close_deadline(tmp_path, monkeypatch):
    """Per-judge nudge I/O must not spend the portfolio close deadline."""
    from internal.judges import tracker, weights

    port_path = tmp_path / "judge_portfolios.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_LOCK_TIMEOUT_SECONDS", 0.25, raising=False)
    row = _gradeable_row(pred_id="nudge-1", outcome="miss", actual_pct=-3.0)
    _open_all_judges(row)

    def slow_nudge(*_a, **_kw):
        time.sleep(0.3)
        return None

    monkeypatch.setattr(weights, "nudge_judge", slow_nudge)
    started = time.monotonic()
    tracker.on_prediction_resolved(row, apply_judge_nudge=True)
    elapsed = time.monotonic() - started
    data = json.loads(port_path.read_text())
    assert all(len(data[name]["open_positions"]) == 0 for name in ("oracle", "echo", "pulse"))
    assert all(len(data[name]["closed_positions"]) == 1 for name in ("oracle", "echo", "pulse"))
    # Three 0.3s nudges may run; they just must not prevent the closes.
    assert elapsed >= 0.3


def test_hour_tick_continues_when_reconcile_raises_non_timeout(monkeypatch):
    """A non-timeout reconcile error must not drop the hour pick."""
    from internal.council import hourly_pick, pick_scheduler

    def boom(**_kw):
        raise ValueError("invalid judge portfolio")

    monkeypatch.setattr(prediction_loop, "reconcile_judge_positions", boom, raising=False)
    monkeypatch.setattr(pick_scheduler, "_load_subnets", lambda: [{"netuid": 7, "price": 12}])
    monkeypatch.setattr(pick_scheduler, "_market_context", lambda _rows: {})
    monkeypatch.setattr(pick_scheduler, "_record_ab_benchmark", lambda *_a: None)
    monkeypatch.setattr(hourly_pick, "select_hourly_pick", lambda *_a: {"action": "long", "subnet": {"netuid": 7, "price": 12}})
    monkeypatch.setattr(pick_scheduler, "_record_hour_pick", lambda *_a, **_kw: "applied")
    result = pick_scheduler.HourPickScheduler(refresh_minutes=15).run_once()
    assert result["ok"] is True
    assert result.get("reconcile_ok") is False
    assert "invalid judge portfolio" in str(result.get("reconcile_error") or "")
    assert result.get("pick_record_outcome") == "applied"


def test_daily_tick_does_not_hold_when_reconcile_raises_non_timeout(monkeypatch):
    """A non-timeout reconcile error must not write a daily scheduler_hold."""
    from internal.council import daily_pick_engine, pick_scheduler

    def boom(**_kw):
        raise ValueError("could not convert string to float: 'abc'")

    monkeypatch.setattr(prediction_loop, "reconcile_judge_positions", boom, raising=False)
    monkeypatch.setattr(pick_scheduler, "_load_subnets", lambda: [])
    monkeypatch.setattr(pick_scheduler, "_market_context", lambda _rows: {})
    monkeypatch.setattr(pick_scheduler, "_record_ab_benchmark", lambda *_a: None)
    monkeypatch.setattr(pick_scheduler, "_today_pick_ready", lambda: True)
    monkeypatch.setattr(daily_pick_engine, "get_or_create_today_pick", lambda *_a, **_kw: {
        "action": "HOLD", "date": "2026-01-01",
    })
    result = pick_scheduler.DailyPickScheduler().run_once()
    assert result["ok"] is True
    assert result.get("reconcile_ok") is False
    assert not result.get("scheduler_hold")
