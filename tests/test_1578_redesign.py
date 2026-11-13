"""#1578 redesign contracts: phase machine, held-gate, observability, history, rebuild."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from internal.judges import portfolios, postmortems, tracker
from internal.learning import expired_recovery, prediction_loop, predictions_store


def _gradeable(pred_id, *, outcome="miss", actual_pct=-3.0, correct=None):
    if correct is None:
        correct = outcome == "hit"
    return {
        "id": pred_id,
        "netuid": 7,
        "name": "Seven",
        "direction": "up",
        "predicted_pct": 5.0,
        "reference_price": 100.0,
        "horizon_hours": 1,
        "outcome": outcome,
        "actual_pct": actual_pct,
        "correct": correct,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "status": "resolved",
        "resolved_price": 97.0,
    }


def _expired(pred_id="expired-1"):
    return {
        "id": pred_id,
        "netuid": 7,
        "name": "Seven",
        "status": "expired",
        "outcome": "expired",
        "correct": None,
        "direction": "up",
        "reference_price": 100.0,
        "predicted_pct": 5.0,
        "resolve_at": "2026-07-01T12:00:00Z",
        "expert": "rogue",
    }


def test_postmortem_same_id_races_and_null_entries_are_shape_safe(tmp_path, monkeypatch):
    pm_dir = tmp_path / "postmortems"
    pm_dir.mkdir()
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(pm_dir))
    path = pm_dir / "oracle.json"
    valid = {
        "judge": "oracle",
        "prediction_id": "keep-me",
        "netuid": 1,
        "questions": {},
        "created_at": "2026-01-01T00:00:00Z",
    }
    path.write_text(json.dumps([None, valid]))

    kept = postmortems.record("oracle", _gradeable("new-id"), actual_pct=-3.0)
    assert kept["prediction_id"] == "new-id"
    rows = json.loads(path.read_text())
    assert any(isinstance(r, dict) and r.get("prediction_id") == "keep-me" for r in rows)
    assert any(isinstance(r, dict) and r.get("prediction_id") == "new-id" for r in rows)

    errors = []

    def writer(pred_id, barrier):
        try:
            barrier.wait(timeout=5)
            postmortems.record("oracle", _gradeable(pred_id), actual_pct=-1.0)
        except Exception as exc:
            errors.append(exc)

    for _ in range(30):
        errors.clear()
        start = threading.Barrier(2)
        threads = [
            threading.Thread(target=writer, args=("race-id", start)),
            threading.Thread(target=writer, args=("race-id", start)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        assert errors == []
        ids = [
            row.get("prediction_id")
            for row in json.loads(path.read_text())
            if isinstance(row, dict)
        ]
        assert ids.count("race-id") == 1


def test_close_without_open_does_not_fabricate_or_tombstone(tmp_path, monkeypatch):
    port_path = tmp_path / "judge_portfolios.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    row = _gradeable("p-close")
    assert portfolios.close_position("oracle", row, actual_pct=1, outcome="hit") is None
    if port_path.exists():
        data = json.loads(port_path.read_text())
        oracle = data.get("oracle") or {}
        assert oracle.get("closed_positions") in (None, [])
        assert not (oracle.get("closed_prediction_ids") or {})
        assert "echo" not in data or not (data["echo"].get("closed_positions") or [])


def test_terminal_ledger_blocks_late_open_but_close_without_open_does_not(tmp_path, monkeypatch):
    port_path = tmp_path / "judge_portfolios.json"
    ledger = tmp_path / "predictions.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(ledger))
    ledger.write_text(json.dumps({"predictions": [], "resolved": [], "stats": {}}))

    row = {"id": "late-1", "netuid": 7, "reference_price": 12, "horizon_hours": 1, "predicted_pct": 2.0}
    assert portfolios.close_position("oracle", row, actual_pct=1, outcome="hit") is None
    opened = portfolios.open_position("oracle", row)
    assert opened is not None
    assert opened.get("id") == "late-1"

    terminal = _gradeable("term-1", outcome="hit", actual_pct=2.0, correct=True)
    ledger.write_text(json.dumps({"predictions": [], "resolved": [terminal], "stats": {}}))
    assert portfolios.open_position("oracle", terminal) is None


def test_tracker_and_reconcile_do_not_fabricate_for_non_holders(tmp_path, monkeypatch):
    port_path = tmp_path / "judge_portfolios.json"
    pm_dir = tmp_path / "postmortems"
    pm_dir.mkdir()
    ledger = tmp_path / "predictions.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(pm_dir))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(ledger))

    row = _gradeable("only-oracle", outcome="miss", actual_pct=-3.0)
    portfolios.open_position("oracle", row)
    ledger.write_text(json.dumps({"predictions": [], "resolved": [row], "stats": {}}))

    tracker.on_prediction_resolved(row, apply_judge_nudge=False)
    prediction_loop.reconcile_judge_positions(predictions_path=str(ledger))

    data = json.loads(port_path.read_text()) if port_path.exists() else {}
    oracle = data.get("oracle") or {}
    assert len(oracle.get("closed_positions") or []) == 1
    assert len(oracle.get("open_positions") or []) == 0
    for name in ("echo", "pulse"):
        judge = data.get(name) or {}
        assert judge.get("closed_positions") in (None, [])
        assert not (judge.get("closed_prediction_ids") or {})
        assert list(postmortems.list_for_judge(name)) == []
    assert len(postmortems.list_for_judge("oracle")) == 1


def test_reconcile_is_bounded_for_already_closed_wrong_picks(tmp_path, monkeypatch):
    port_path = tmp_path / "judge_portfolios.json"
    pm_dir = tmp_path / "postmortems"
    pm_dir.mkdir()
    ledger = tmp_path / "predictions.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(pm_dir))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(ledger))

    rows = []
    for i in range(50):
        row = _gradeable(f"closed-{i}", outcome="miss", actual_pct=-2.0)
        rows.append(row)
        if hasattr(portfolios, "backfill_closed_position"):
            for name in ("oracle", "echo", "pulse"):
                portfolios.backfill_closed_position(name, row, actual_pct=-2.0, outcome="miss")
        else:
            portfolios.open_position("oracle", row)
            portfolios.close_position("oracle", row, actual_pct=-2.0, outcome="miss")
    ledger.write_text(json.dumps({"predictions": [], "resolved": rows, "stats": {}}))

    calls = {"close": 0, "resolved": 0}
    real_close = portfolios.close_position
    real_resolved = tracker.on_prediction_resolved

    def counting_close(*args, **kwargs):
        calls["close"] += 1
        return real_close(*args, **kwargs)

    def counting_resolved(*args, **kwargs):
        calls["resolved"] += 1
        return real_resolved(*args, **kwargs)

    monkeypatch.setattr(portfolios, "close_position", counting_close)
    monkeypatch.setattr(tracker, "on_prediction_resolved", counting_resolved)
    monkeypatch.setattr(prediction_loop, "on_prediction_resolved", counting_resolved, raising=False)

    started = time.monotonic()
    prediction_loop.reconcile_judge_positions(predictions_path=str(ledger))
    elapsed = time.monotonic() - started
    assert calls["close"] == 0
    assert calls["resolved"] == 0
    assert elapsed < 2.0


def test_recovery_refused_persist_does_not_nudge_and_applied_keeps_stamps(tmp_path, monkeypatch):
    from internal.council import resolver
    from internal.council import price_reference
    from internal.learning.predictions_store import PersistOutcome, PersistReason, PersistResult

    pred_path = tmp_path / "predictions.json"
    port_path = tmp_path / "judge_portfolios.json"
    port_path.write_text("{}")
    row = _expired("rec-1")
    pred_path.write_text(json.dumps({"predictions": [], "resolved": [row], "stats": {}}))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(
        price_reference,
        "price_at_resolve_at",
        lambda *args, **kwargs: ("ok", 110.0, {"price_source": "hourly"}),
    )
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *args, **kwargs: False)

    counts = {"weights": 0, "impact": 0, "scenario": 0, "signal": 0}
    real_weights = resolver._nudge_weights
    real_impact = resolver._nudge_impact_strength
    real_scenario = resolver._record_scenario_outcome
    real_signal = resolver._nudge_signal_weights

    def count_weights(*args, **kwargs):
        counts["weights"] += 1
        return real_weights(*args, **kwargs)

    def count_impact(*args, **kwargs):
        counts["impact"] += 1
        return real_impact(*args, **kwargs)

    def count_scenario(*args, **kwargs):
        counts["scenario"] += 1
        return real_scenario(*args, **kwargs)

    def count_signal(*args, **kwargs):
        counts["signal"] += 1
        return real_signal(*args, **kwargs)

    monkeypatch.setattr(resolver, "_nudge_weights", count_weights)
    monkeypatch.setattr(resolver, "_nudge_impact_strength", count_impact)
    monkeypatch.setattr(resolver, "_record_scenario_outcome", count_scenario)
    monkeypatch.setattr(resolver, "_nudge_signal_weights", count_signal)

    monkeypatch.setattr(
        predictions_store,
        "merge_ledger_changes",
        lambda *args, **kwargs: PersistResult(PersistOutcome.REFUSED, PersistReason.CONFLICT_ONLY),
    )
    result = expired_recovery.recover_expired_predictions()
    assert result["ok"] is False
    assert result.get("recovered") == 0
    assert counts == {"weights": 0, "impact": 0, "scenario": 0, "signal": 0}
    disk = json.loads(pred_path.read_text())["resolved"][0]
    assert disk["outcome"] == "expired"
    assert disk["status"] == "expired"

    monkeypatch.setattr(predictions_store, "merge_ledger_changes", predictions_store.merge_ledger_changes)
    # Re-import bound original: just delete the patch by setting the real function.
    from internal.learning import predictions_store as ps

    monkeypatch.undo()
    # Re-apply path and price stubs plus counters after undo.
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(
        price_reference,
        "price_at_resolve_at",
        lambda *args, **kwargs: ("ok", 110.0, {"price_source": "hourly"}),
    )
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *args, **kwargs: False)
    monkeypatch.setattr(resolver, "_nudge_weights", count_weights)
    monkeypatch.setattr(resolver, "_nudge_impact_strength", count_impact)
    monkeypatch.setattr(resolver, "_record_scenario_outcome", count_scenario)
    monkeypatch.setattr(resolver, "_nudge_signal_weights", count_signal)
    counts.update({k: 0 for k in counts})

    result = expired_recovery.recover_expired_predictions()
    assert result.get("ok") is True
    assert result.get("recovered") == 1
    assert counts["weights"] + counts["impact"] + counts["scenario"] + counts["signal"] > 0
    # And not a double-count from the refused attempt.
    assert counts["impact"] == 1
    disk = json.loads(pred_path.read_text())["resolved"][0]
    assert disk.get("expert")
    assert disk.get("expert_attribution_source") or disk.get("expert")
    assert isinstance(disk.get("subnet_snapshot"), dict)


def test_missing_or_corrupt_portfolio_is_not_all_closed(tmp_path, monkeypatch):
    from internal.council import resolver
    from internal.council import price_reference

    pred_path = tmp_path / "predictions.json"
    port_path = tmp_path / "judge_portfolios.json"
    pred_path.write_text(json.dumps({"predictions": [], "resolved": [_expired("miss-1")], "stats": {}}))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(
        price_reference,
        "price_at_resolve_at",
        lambda *args, **kwargs: ("ok", 110.0, {"price_source": "hourly"}),
    )
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *args, **kwargs: True)
    monkeypatch.setattr(resolver, "_stamp_and_nudge_expert", lambda *args, **kwargs: ("quant", None), raising=False)
    if hasattr(resolver, "_stamp_expert_attribution"):
        monkeypatch.setattr(resolver, "_stamp_expert_attribution", lambda *args, **kwargs: ("quant", "existing"))
    monkeypatch.setattr(resolver, "_ensure_subnet_snapshot", lambda *args, **kwargs: None)

    assert not port_path.exists()
    result = expired_recovery.recover_expired_predictions()
    assert result.get("ok") is not True
    assert result.get("recovered") == 0
    disk = json.loads(pred_path.read_text())["resolved"][0]
    assert disk["outcome"] == "expired"

    port_path.write_bytes(b"{not json")
    pred_path.write_text(json.dumps({"predictions": [], "resolved": [_expired("corr-1")], "stats": {}}))
    result = expired_recovery.recover_expired_predictions()
    assert result.get("ok") is not True
    assert result.get("recovered") == 0


def test_rebuild_from_terminal_stream_writes_closed_summaries_and_postmortems(tmp_path, monkeypatch):
    from internal.council.replay import rebuild_judge_portfolios_from_stream

    port_path = tmp_path / "judge_portfolios.json"
    pm_dir = tmp_path / "postmortems"
    pm_dir.mkdir()
    ledger = tmp_path / "predictions.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(pm_dir))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(ledger))

    hit = _gradeable("a-hit", outcome="hit", actual_pct=2.0, correct=True)
    hit.update({"created_at": "2026-07-01T10:00:00Z", "name": "A"})
    miss = _gradeable("a-miss", outcome="miss", actual_pct=-4.0, correct=False)
    miss.update({"created_at": "2026-07-01T10:30:00Z", "name": "B"})
    pending = {
        "id": "a-pending",
        "netuid": 9,
        "name": "C",
        "direction": "up",
        "predicted_pct": 1.0,
        "reference_price": 10.0,
        "horizon_hours": 1,
        "created_at": "2026-07-01T11:00:00Z",
        "status": "pending",
    }
    ledger.write_text(json.dumps({"predictions": [pending], "resolved": [hit, miss], "stats": {}}))

    rebuild_judge_portfolios_from_stream(
        [hit, miss, pending],
        portfolios_path=str(port_path),
    )
    data = json.loads(port_path.read_text())
    for name in ("oracle", "echo", "pulse"):
        judge = data[name]
        assert len(judge["closed_positions"]) == 2
        assert judge["summary"]["total_closed"] == 2
        assert len(judge["open_positions"]) == 1
        assert judge["open_positions"][0]["id"] == "a-pending"
    assert len(postmortems.list_for_judge("oracle")) == 1
    assert len(postmortems.list_for_judge("echo")) == 1
    assert len(postmortems.list_for_judge("pulse")) == 1


def test_finalize_from_prediction_raises_when_save_fails(tmp_path, monkeypatch):
    from internal.council import pick_history

    good = tmp_path / "pick_history.json"
    monkeypatch.setattr(pick_history, "PICK_HISTORY_PATH", str(good))
    rec = pick_history.record_hour_pick(
        {"confidence": 0.8, "action": "long"},
        {"netuid": 1, "name": "Alpha", "price": 100.0},
        prediction_id="p1",
    )
    assert rec is not None

    def boom(_data):
        raise OSError("pick history save failed")

    monkeypatch.setattr(pick_history, "_save", boom)
    with pytest.raises(OSError, match="pick history save failed"):
        pick_history.finalize_from_prediction(
            {
                "id": "p1",
                "horizon_type": "hour",
                "netuid": 1,
                "correct": True,
                "outcome": "hit",
                "actual_pct": 2.0,
                "resolved_price": 102.0,
            }
        )


def test_hour_history_failed_write_is_repaired_or_stays_not_ok(tmp_path, monkeypatch):
    from internal.council import hourly_pick, pick_history, pick_scheduler
    from internal.subnets import tradable

    pred_path = tmp_path / "predictions.json"
    port_path = tmp_path / "judge_portfolios.json"
    pred_path.write_text(json.dumps({"predictions": [], "resolved": [], "stats": {}}))
    port_path.write_text("{}")
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(tradable, "is_tradable_subnet", lambda *_a, **_kw: True, raising=False)

    blocked = tmp_path / "hist_parent"
    blocked.write_text("not-a-dir")
    bad_hist = blocked / "pick_history.json"
    good_hist = tmp_path / "pick_history.json"
    monkeypatch.setattr(pick_history, "PICK_HISTORY_PATH", str(bad_hist))

    def boom_open(*_a, **_kw):
        raise OSError("open failed after append")

    monkeypatch.setattr(portfolios, "open_positions_for_prediction", boom_open)
    monkeypatch.setattr(pick_scheduler, "_load_subnets", lambda: [{"netuid": 7, "name": "Seven", "price": 12}])
    monkeypatch.setattr(pick_scheduler, "_market_context", lambda _rows: {})
    monkeypatch.setattr(pick_scheduler, "_record_ab_benchmark", lambda *_a: None)
    monkeypatch.setattr(
        hourly_pick,
        "select_hourly_pick",
        lambda *_a, **_kw: {"action": "long", "subnet": {"netuid": 7, "name": "Seven", "price": 12}, "confidence": 0.7},
    )
    monkeypatch.setattr(prediction_loop, "reconcile_judge_positions", lambda **_kw: 0, raising=False)

    first = pick_scheduler.HourPickScheduler(refresh_minutes=15).run_once()
    assert first.get("ok") is False
    assert first.get("pick_record_outcome") == "indeterminate"
    ledger = json.loads(pred_path.read_text())
    pending = ledger.get("predictions") or []
    assert pending, "expected a real ledger append"
    pred_id = pending[0]["id"]
    assert not good_hist.exists()
    assert not Path(str(bad_hist)).exists() or Path(str(bad_hist)).is_dir() is False

    monkeypatch.setattr(pick_history, "PICK_HISTORY_PATH", str(good_hist))
    second = pick_scheduler.HourPickScheduler(refresh_minutes=15).run_once()
    store = json.loads(good_hist.read_text()) if good_hist.exists() else {}
    active_id = (store.get("active") or {}).get("prediction_id")
    history_ids = [row.get("prediction_id") for row in (store.get("history") or []) if isinstance(row, dict)]
    if second.get("ok") is True:
        assert active_id == pred_id or pred_id in history_ids
        assert history_ids.count(pred_id) <= 1
    else:
        assert second.get("ok") is False
        assert second.get("pick_record_outcome") in {"indeterminate", "failed", None}


def test_idless_incomplete_does_not_churn_history(tmp_path, monkeypatch):
    from internal.council import pick_history, pick_scheduler
    from internal.learning.prediction_loop import PickRecord, PickRecordKind

    hist_path = tmp_path / "hour_history.json"
    monkeypatch.setattr(pick_history, "PICK_HISTORY_PATH", str(hist_path))
    # Seed an active row so a buggy retire would be visible.
    pick_history.record_hour_pick(
        {"action": "long", "confidence": 0.5},
        {"netuid": 3, "name": "Three", "price": 9.0},
        prediction_id="keep-active",
    )
    stored = PickRecord(PickRecordKind.INDETERMINATE, {"id": None}, "positions_incomplete")
    monkeypatch.setattr(prediction_loop, "record_pick", lambda *a, **k: stored)
    before = json.loads(hist_path.read_text())
    for _ in range(2):
        outcome = pick_scheduler._record_hour_pick(
            {"action": "long", "subnet": {"netuid": 7, "price": 12}},
            [{"netuid": 7, "price": 12}],
            {},
        )
        assert outcome in {"indeterminate", "failed"}
    after = json.loads(hist_path.read_text())
    assert (after.get("active") or {}).get("prediction_id") == "keep-active"
    retired = [row for row in (after.get("history") or []) if isinstance(row, dict)]
    assert retired == (before.get("history") or [])
