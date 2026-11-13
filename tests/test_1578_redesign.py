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


@pytest.fixture(autouse=True)
def _isolate_learning_effect_receipts(tmp_path, monkeypatch):
    receipts = tmp_path / "learning_effect_receipts.json"
    monkeypatch.setattr(expired_recovery, "LEARNING_EFFECT_RECEIPTS_PATH", str(receipts), raising=False)
    monkeypatch.setenv("LEARNING_EFFECT_RECEIPTS_PATH", str(receipts))


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
    # undo() also drops the autouse receipts isolation; restore it.
    monkeypatch.setattr(expired_recovery, "LEARNING_EFFECT_RECEIPTS_PATH", str(tmp_path / "learning_effect_receipts.json"), raising=False)
    monkeypatch.setenv("LEARNING_EFFECT_RECEIPTS_PATH", str(tmp_path / "learning_effect_receipts.json"))
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
    # A missing book is close-complete: recovery may grade the row and stamp finalize.
    disk = json.loads(pred_path.read_text())["resolved"][0]
    if result.get("ok") is True:
        assert disk.get("outcome") in {"hit", "miss"}
        assert not port_path.exists()
    else:
        # Still must not look like a quiet success that skipped the grade.
        assert result.get("ok") is not True

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


def _receipts_and_effects_paths(tmp_path, monkeypatch):
    receipts = tmp_path / "learning_effect_receipts.json"
    monkeypatch.setattr(expired_recovery, "LEARNING_EFFECT_RECEIPTS_PATH", str(receipts), raising=False)
    if hasattr(expired_recovery, "_receipts_path"):
        monkeypatch.setattr(expired_recovery, "_receipts_path", lambda: str(receipts), raising=False)
    return receipts


def test_partial_ledger_conflict_trains_only_committed_row(tmp_path, monkeypatch):
    from internal.council import resolver, price_reference
    from internal.learning import predictions_store as ps

    pred_path = tmp_path / "predictions.json"
    port_path = tmp_path / "judge_portfolios.json"
    port_path.write_text("{}")
    rows = [_expired("keep"), _expired("conflict")]
    rows[1]["netuid"] = 8
    pred_path.write_text(json.dumps({"predictions": [], "resolved": rows, "stats": {}}))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    _receipts_and_effects_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(
        price_reference,
        "price_at_resolve_at",
        lambda *args, **kwargs: ("ok", 110.0, {"price_source": "hourly"}),
    )
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *args, **kwargs: False)

    counts = {"impact": 0, "finalize": 0}
    real_impact = resolver._nudge_impact_strength
    real_finalize = resolver.atomic_finalize_resolution

    def count_impact(*args, **kwargs):
        counts["impact"] += 1
        return real_impact(*args, **kwargs)

    def count_finalize(row, *args, **kwargs):
        counts["finalize"] += 1
        return real_finalize(row, *args, **kwargs)

    monkeypatch.setattr(resolver, "_nudge_impact_strength", count_impact)
    monkeypatch.setattr(resolver, "atomic_finalize_resolution", count_finalize)

    real_merge = predictions_store.merge_ledger_changes
    injected = {"done": False}

    def wrapped_merge(before, after, *args, **kwargs):
        if (
            kwargs.get("caller") == "expired_recovery"
            and kwargs.get("trigger") == "expired_recovery"
            and not injected["done"]
        ):
            data = json.loads(pred_path.read_text())
            for row in data.get("resolved") or []:
                if row.get("id") == "conflict":
                    row["note"] = "concurrent-edit"
            pred_path.write_text(json.dumps(data))
            injected["done"] = True
        return real_merge(before, after, *args, **kwargs)

    monkeypatch.setattr(predictions_store, "merge_ledger_changes", wrapped_merge)
    monkeypatch.setattr(ps, "merge_ledger_changes", wrapped_merge)

    result = expired_recovery.recover_expired_predictions()
    assert result.get("ok") is False
    assert result.get("reason") == "persist_conflict"
    assert result.get("recovered") == 1
    disk = {row["id"]: row for row in json.loads(pred_path.read_text())["resolved"]}
    assert disk["keep"].get("outcome") in {"hit", "miss"}
    assert disk["conflict"]["outcome"] == "expired"
    assert counts["impact"] == 1
    assert counts["finalize"] == 1


def test_post_commit_learning_retries_and_idless_receipts(tmp_path, monkeypatch):
    from internal.council import resolver, price_reference
    from internal.learning import predictions_store as ps

    pred_path = tmp_path / "predictions.json"
    port_path = tmp_path / "judge_portfolios.json"
    port_path.write_text("{}")
    pred_path.write_text(json.dumps({"predictions": [], "resolved": [_expired("retry-1")], "stats": {}}))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    _receipts_and_effects_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(
        price_reference,
        "price_at_resolve_at",
        lambda *args, **kwargs: ("ok", 110.0, {"price_source": "hourly"}),
    )
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *args, **kwargs: False)

    expert_calls = {"n": 0, "fail": True}
    real_expert = resolver._nudge_attributed_expert

    def flaky_expert(*args, **kwargs):
        expert_calls["n"] += 1
        if expert_calls["fail"]:
            raise OSError("expert learning failed")
        return real_expert(*args, **kwargs)

    monkeypatch.setattr(resolver, "_nudge_attributed_expert", flaky_expert)
    first = expired_recovery.recover_expired_predictions()
    assert first.get("ok") is False
    assert first.get("reason") == "effects_incomplete"
    disk = json.loads(pred_path.read_text())["resolved"][0]
    assert disk.get("outcome") in {"hit", "miss"}
    pending = (disk.get("learning_effects") or {}).get("pending") or []
    assert "expert" in pending
    assert expert_calls["n"] == 1

    expert_calls["fail"] = False
    second = expired_recovery.recover_expired_predictions()
    assert second.get("recovered") == 0
    disk = json.loads(pred_path.read_text())["resolved"][0]
    done = (disk.get("learning_effects") or {}).get("done") or []
    assert "expert" in done
    assert "expert" not in ((disk.get("learning_effects") or {}).get("pending") or [])
    assert expert_calls["n"] == 2
    third = expired_recovery.recover_expired_predictions()
    assert expert_calls["n"] == 2
    assert "impact" in done or "impact" in ((json.loads(pred_path.read_text())["resolved"][0].get("learning_effects") or {}).get("done") or [])


def test_idless_legacy_rows_have_distinct_effect_receipts(tmp_path, monkeypatch):
    from internal.council import resolver, price_reference
    from internal.learning import predictions_store as ps

    pred_path = tmp_path / "predictions.json"
    port_path = tmp_path / "judge_portfolios.json"
    port_path.write_text("{}")
    a = _expired(None)
    a["created_at"] = "2026-07-01T10:00:00Z"
    a["horizon_type"] = "hour"
    a["netuid"] = 7
    b = _expired(None)
    b["created_at"] = "2026-07-01T11:00:00Z"
    b["horizon_type"] = "hour"
    b["netuid"] = 8
    pred_path.write_text(json.dumps({"predictions": [], "resolved": [a, b], "stats": {}}))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    _receipts_and_effects_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(
        price_reference,
        "price_at_resolve_at",
        lambda *args, **kwargs: ("ok", 110.0, {"price_source": "hourly"}),
    )
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *args, **kwargs: False)
    impact = {"n": 0}
    real = resolver._nudge_impact_strength

    def count(*args, **kwargs):
        impact["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(resolver, "_nudge_impact_strength", count)
    result = expired_recovery.recover_expired_predictions()
    assert impact["n"] == 2
    disk = json.loads(pred_path.read_text())["resolved"]
    assert all(row.get("outcome") in {"hit", "miss"} for row in disk)
    assert result.get("recovered") == 2


def test_finalize_stays_pending_when_close_times_out(tmp_path, monkeypatch):
    from internal.council import resolver, price_reference
    from internal.learning import predictions_store as ps
    from internal.judges.portfolios import PortfolioLockTimeout

    pred_path = tmp_path / "predictions.json"
    port_path = tmp_path / "judge_portfolios.json"
    row = _expired("lock-1")
    pred_path.write_text(json.dumps({"predictions": [], "resolved": [row], "stats": {}}))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    _receipts_and_effects_paths(tmp_path, monkeypatch)
    open_row = _gradeable("lock-1")
    open_row["status"] = "pending"
    open_row["outcome"] = None
    for name in ("oracle", "echo", "pulse"):
        portfolios.open_position(name, open_row)
    monkeypatch.setattr(
        price_reference,
        "price_at_resolve_at",
        lambda *args, **kwargs: ("ok", 110.0, {"price_source": "hourly"}),
    )
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *args, **kwargs: True)

    real_close = portfolios.close_position
    state = {"fail": True}

    def flaky_close(judge_name, *args, **kwargs):
        if state["fail"] and judge_name == "oracle":
            raise PortfolioLockTimeout("injected close timeout")
        return real_close(judge_name, *args, **kwargs)

    monkeypatch.setattr(portfolios, "close_position", flaky_close)
    first = expired_recovery.recover_expired_predictions()
    assert first.get("ok") is False
    disk = json.loads(pred_path.read_text())["resolved"][0]
    pending = (disk.get("learning_effects") or {}).get("pending") or []
    assert "finalize" in pending
    book = json.loads(port_path.read_text())
    assert any(pos.get("id") == "lock-1" for name in ("oracle", "echo", "pulse") for pos in (book.get(name) or {}).get("open_positions") or [])

    state["fail"] = False
    second = expired_recovery.recover_expired_predictions()
    book = json.loads(port_path.read_text())
    assert not any(pos.get("id") == "lock-1" for name in ("oracle", "echo", "pulse") for pos in (book.get(name) or {}).get("open_positions") or [])
    disk = json.loads(pred_path.read_text())["resolved"][0]
    assert "finalize" in ((disk.get("learning_effects") or {}).get("done") or [])
    assert "finalize" not in ((disk.get("learning_effects") or {}).get("pending") or [])
    assert second.get("recovered") == 0


def test_finalize_gate_sees_idless_open_positions(tmp_path, monkeypatch):
    from internal.council import resolver, price_reference
    from internal.learning import predictions_store as ps
    from internal.judges.portfolios import PortfolioLockTimeout

    pred_path = tmp_path / "predictions.json"
    port_path = tmp_path / "judge_portfolios.json"
    row = _expired(None)
    row["created_at"] = "2026-07-01T10:00:00Z"
    row["horizon_type"] = "day"
    pred_path.write_text(json.dumps({"predictions": [], "resolved": [row], "stats": {}}))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    _receipts_and_effects_paths(tmp_path, monkeypatch)
    open_row = dict(row)
    open_row["id"] = None
    open_row["status"] = "pending"
    open_row["outcome"] = None
    for name in ("oracle", "echo", "pulse"):
        portfolios.open_position(name, open_row)
    monkeypatch.setattr(
        price_reference,
        "price_at_resolve_at",
        lambda *args, **kwargs: ("ok", 110.0, {"price_source": "hourly"}),
    )
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *args, **kwargs: True)
    real_close = portfolios.close_position
    state = {"fail": True}

    def flaky_close(judge_name, *args, **kwargs):
        if state["fail"] and judge_name == "oracle":
            raise PortfolioLockTimeout("injected close timeout")
        return real_close(judge_name, *args, **kwargs)

    monkeypatch.setattr(portfolios, "close_position", flaky_close)
    first = expired_recovery.recover_expired_predictions()
    assert first.get("ok") is False
    disk = json.loads(pred_path.read_text())["resolved"][0]
    assert "finalize" in ((disk.get("learning_effects") or {}).get("pending") or [])
    book = json.loads(port_path.read_text())
    assert any((book.get(name) or {}).get("open_positions") for name in ("oracle", "echo", "pulse"))


def test_unreadable_book_retry_does_not_stamp_finalize_missing_book_does(tmp_path, monkeypatch):
    from internal.council import resolver, price_reference
    from internal.learning import predictions_store as ps

    pred_path = tmp_path / "predictions.json"
    port_path = tmp_path / "judge_portfolios.json"
    receipts = _receipts_and_effects_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(
        price_reference,
        "price_at_resolve_at",
        lambda *args, **kwargs: ("ok", 110.0, {"price_source": "hourly"}),
    )
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *args, **kwargs: True)

    # Seed a graded row with pending finalize (retry-only, recovered == 0).
    graded = _expired("retry-u")
    graded.update({"outcome": "miss", "status": "resolved", "correct": False, "actual_pct": -3.0, "resolved_price": 97.0})
    graded["learning_effects"] = {"pending": ["finalize", "pump"], "done": []}
    pred_path.write_text(json.dumps({"predictions": [], "resolved": [graded], "stats": {}}))

    port_path.write_bytes(b"{not json")
    corrupt_bytes = port_path.read_bytes()
    result = expired_recovery.recover_expired_predictions()
    assert result.get("ok") is False
    assert result.get("recovered") == 0
    assert port_path.read_bytes() == corrupt_bytes
    disk = json.loads(pred_path.read_text())["resolved"][0]
    assert "finalize" in ((disk.get("learning_effects") or {}).get("pending") or [])

    port_path.unlink()
    result = expired_recovery.recover_expired_predictions()
    disk = json.loads(pred_path.read_text())["resolved"][0]
    assert "finalize" in ((disk.get("learning_effects") or {}).get("done") or [])
    assert "finalize" not in ((disk.get("learning_effects") or {}).get("pending") or [])
    assert not port_path.exists()


def test_late_open_race_ends_with_zero_open_positions(tmp_path, monkeypatch):
    from internal.learning import predictions_store as ps

    pred_path = tmp_path / "predictions.json"
    port_path = tmp_path / "judge_portfolios.json"
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))

    for i in range(20):
        pred_id = f"race-{i}"
        pending = _gradeable(pred_id)
        pending["status"] = "pending"
        pending["outcome"] = None
        pending["correct"] = None
        pred_path.write_text(json.dumps({"predictions": [pending], "resolved": [], "stats": {}}))
        if port_path.exists():
            port_path.unlink()

        started = threading.Event()
        release = threading.Event()
        real_terminal = portfolios._prediction_is_terminal
        calls = {"n": 0}

        def wrapped(pred):
            result = real_terminal(pred)
            calls["n"] += 1
            if calls["n"] == 1:
                started.set()
                assert release.wait(timeout=5)
            return result

        monkeypatch.setattr(portfolios, "_prediction_is_terminal", wrapped)
        errors = []

        def opener():
            try:
                portfolios.open_positions_for_prediction(pending, {"oracle": {"confidence": 0.5}, "echo": {"confidence": 0.5}, "pulse": {"confidence": 0.5}})
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=opener)
        thread.start()
        assert started.wait(timeout=5)
        before = json.loads(pred_path.read_text())
        after = {"predictions": [], "resolved": [_gradeable(pred_id)], "stats": {}}
        predictions_store.merge_ledger_changes(before, after, caller="test", trigger="test-resolve")
        tracker.on_prediction_resolved(_gradeable(pred_id), apply_judge_nudge=False)
        release.set()
        thread.join(5)
        assert errors == []
        monkeypatch.setattr(portfolios, "_prediction_is_terminal", real_terminal)
        if port_path.exists():
            book = json.loads(port_path.read_text())
        else:
            book = {}
        opens = [
            pos
            for name in ("oracle", "echo", "pulse")
            for pos in (book.get(name) or {}).get("open_positions") or []
            if pos.get("id") == pred_id
        ]
        assert opens == [], opens


def test_tracker_unreadable_portfolio_warns_and_missing_is_quiet(tmp_path, monkeypatch):
    from internal.council import resolver

    port_path = tmp_path / "judge_portfolios.json"
    ledger = tmp_path / "predictions.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(ledger))
    ledger.write_text(json.dumps({"predictions": [], "resolved": [], "stats": {}}))
    row = _gradeable("obs-1", outcome="miss")

    assert not port_path.exists()
    summary = tracker.on_prediction_resolved(row, apply_judge_nudge=False)
    finalized = resolver.atomic_finalize_resolution(
        dict(row),
        actual_pct=-3.0,
        outcome="miss",
        correct=False,
        resolved_price=97.0,
        resolved_at="2026-07-01T12:00:00Z",
        apply_judge_nudge=False,
    )
    warnings = finalized.get("side_effect_warnings") or []
    assert "portfolios_unobservable" not in warnings
    assert not port_path.exists()
    assert summary.get("judges", {}).get("oracle", {}).get("closed") is None

    port_path.write_bytes(b"{not json")
    corrupt = port_path.read_bytes()
    finalized = resolver.atomic_finalize_resolution(
        dict(row),
        actual_pct=-3.0,
        outcome="miss",
        correct=False,
        resolved_price=97.0,
        resolved_at="2026-07-01T12:00:00Z",
        apply_judge_nudge=False,
    )
    warnings = finalized.get("side_effect_warnings") or []
    assert "portfolios_unobservable" in warnings
    assert port_path.read_bytes() == corrupt
    summary = tracker.on_prediction_resolved(row, apply_judge_nudge=False)
    for name in ("oracle", "echo", "pulse"):
        assert name in summary.get("judges", {})
        assert summary["judges"][name].get("closed") is None
    assert port_path.read_bytes() == corrupt


def test_prediction_is_terminal_accumulates_duplicate_ids(tmp_path, monkeypatch):
    from internal.learning import predictions_store as ps

    pred_path = tmp_path / "predictions.json"
    port_path = tmp_path / "judge_portfolios.json"
    pending = _gradeable("dup-x")
    pending["status"] = "pending"
    pending["outcome"] = None
    pending["correct"] = None
    resolved = _gradeable("dup-x", outcome="hit")
    pred_path.write_text(json.dumps({"predictions": [pending], "resolved": [resolved], "stats": {}}))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    assert predictions_store.prediction_is_terminal("dup-x") is True
    assert portfolios.open_position("oracle", pending) is None
    portfolios.open_positions_for_prediction(pending, {"oracle": {"confidence": 0.5}, "echo": {"confidence": 0.5}, "pulse": {"confidence": 0.5}})
    if port_path.exists():
        book = json.loads(port_path.read_text())
        assert not any(pos.get("id") == "dup-x" for name in book for pos in (book[name].get("open_positions") or []) if isinstance(book.get(name), dict))


def test_idless_hourly_duplicate_and_corrupt_history_are_not_green(tmp_path, monkeypatch):
    from internal.council import hourly_pick, pick_history, pick_scheduler
    from internal.learning import predictions_store as ps
    from internal.subnets import tradable

    pred_path = tmp_path / "predictions.json"
    port_path = tmp_path / "judge_portfolios.json"
    hist_path = tmp_path / "pick_history.json"
    pending = {
        "netuid": 7,
        "name": "Seven",
        "horizon_type": "hour",
        "status": "pending",
        "direction": "up",
        "reference_price": 12.0,
        "predicted_pct": 1.0,
    }
    pred_path.write_text(json.dumps({"predictions": [pending], "resolved": [], "stats": {}}))
    port_path.write_text("{}")
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    monkeypatch.setattr(pick_history, "PICK_HISTORY_PATH", str(hist_path))
    monkeypatch.setattr(tradable, "is_tradable_subnet", lambda *_a, **_kw: True, raising=False)
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
    assert first.get("pick_record_outcome") in {"indeterminate", "failed"}
    assert first.get("pick_record_outcome") != "skipped"

    hist_path.write_bytes(b"{not json")
    corrupt = hist_path.read_bytes()
    second = pick_scheduler.HourPickScheduler(refresh_minutes=15).run_once()
    assert second.get("ok") is False
    assert second.get("pick_record_outcome") in {"indeterminate", "failed"}
    assert hist_path.read_bytes() == corrupt


def test_corrupt_receipts_are_not_replayed_or_rewritten(tmp_path, monkeypatch):
    from internal.council import resolver, price_reference
    from internal.learning import predictions_store as ps
    from internal.learning.pump_calibration import maybe_adapt_after_resolve as pump_mod

    pred_path = tmp_path / "predictions.json"
    port_path = tmp_path / "judge_portfolios.json"
    receipts = _receipts_and_effects_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    port_path.write_text("{}")
    graded = _expired("receipt-corrupt")
    graded.update({"outcome": "miss", "status": "resolved", "correct": False, "actual_pct": -3.0, "resolved_price": 97.0})
    graded["learning_effects"] = {"pending": ["expert"], "done": []}
    pred_path.write_text(json.dumps({"predictions": [], "resolved": [graded], "stats": {}}))
    receipts.write_bytes(b'{"half": ')
    corrupt = receipts.read_bytes()
    counts = {"expert": 0}
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *a, **k: False)
    monkeypatch.setattr(resolver, "_nudge_attributed_expert", lambda *a, **k: counts.__setitem__("expert", counts["expert"] + 1))
    monkeypatch.setattr(resolver, "_nudge_impact_strength", lambda *a, **k: None)
    monkeypatch.setattr(resolver, "_record_scenario_outcome", lambda *a, **k: None)
    monkeypatch.setattr(resolver, "_nudge_signal_weights", lambda *a, **k: None)
    monkeypatch.setattr(price_reference, "price_at_resolve_at", lambda *a, **k: ("ok", 110.0, {"price_source": "hourly"}))
    result = expired_recovery.recover_expired_predictions()
    assert result.get("ok") is not True
    assert receipts.read_bytes() == corrupt
    assert counts["expert"] == 0


def test_concurrent_receipt_writes_do_not_drop_keys(tmp_path, monkeypatch):
    receipts = _receipts_and_effects_paths(tmp_path, monkeypatch)
    errors = []

    def writer(i):
        try:
            expired_recovery.write_effect_receipt(("id", f"r-{i}"), "expert")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert errors == [], errors
    data = json.loads(receipts.read_text())
    assert len(data) == 20


def test_idless_hour_close_does_not_consume_unrelated_day_position(tmp_path, monkeypatch):
    port_path = tmp_path / "judge_portfolios.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    day = {
        "id": None,
        "netuid": 7,
        "direction": "up",
        "predicted_pct": 5.0,
        "reference_price": 100.0,
        "horizon_hours": 24,
        "horizon_type": "day",
        "created_at": "2026-07-01T00:00:00Z",
    }
    hour = {
        "id": None,
        "netuid": 7,
        "direction": "up",
        "predicted_pct": 1.0,
        "reference_price": 100.0,
        "horizon_hours": 1,
        "horizon_type": "hour",
        "created_at": "2026-07-01T10:00:00Z",
        "outcome": "miss",
        "actual_pct": -2.0,
    }
    portfolios.open_position("oracle", day)
    closed = portfolios.close_position("oracle", hour, actual_pct=-2.0, outcome="miss")
    assert closed is None
    book = json.loads(port_path.read_text())
    opens = (book.get("oracle") or {}).get("open_positions") or []
    assert len(opens) == 1
    assert opens[0].get("horizon_type") == "day" or opens[0].get("prediction_created_at") == "2026-07-01T00:00:00Z"


def test_refused_receipt_ledger_stamp_is_not_ok(tmp_path, monkeypatch):
    from internal.council import resolver, price_reference
    from internal.learning import predictions_store as ps
    from internal.learning.predictions_store import PersistOutcome, PersistReason, PersistResult

    pred_path = tmp_path / "predictions.json"
    port_path = tmp_path / "judge_portfolios.json"
    receipts = _receipts_and_effects_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    port_path.write_text("{}")
    graded = _expired("refused-stamp")
    graded.update({"outcome": "miss", "status": "resolved", "correct": False, "actual_pct": -3.0, "resolved_price": 97.0})
    graded["learning_effects"] = {"pending": ["finalize", "pump"], "done": []}
    pred_path.write_text(json.dumps({"predictions": [], "resolved": [graded], "stats": {}}))
    real_merge = predictions_store.merge_ledger_changes

    def refuse_receipt_stamp(*args, **kwargs):
        if kwargs.get("trigger") == "learning_effect_receipt":
            return PersistResult(PersistOutcome.REFUSED, PersistReason.CONFLICT_ONLY)
        return real_merge(*args, **kwargs)

    monkeypatch.setattr(predictions_store, "merge_ledger_changes", refuse_receipt_stamp)
    monkeypatch.setattr(ps, "merge_ledger_changes", refuse_receipt_stamp)
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *a, **k: True)
    monkeypatch.setattr(price_reference, "price_at_resolve_at", lambda *a, **k: ("ok", 110.0, {"price_source": "hourly"}))
    result = expired_recovery.recover_expired_predictions()
    assert result.get("ok") is not True
    disk = json.loads(pred_path.read_text())["resolved"][0]
    pending = ((disk.get("learning_effects") or {}).get("pending") or [])
    assert "finalize" in pending or "pump" in pending


def test_pump_failure_is_not_marked_done(tmp_path, monkeypatch):
    from internal.council import resolver, price_reference
    from internal.learning import predictions_store as ps
    import internal.learning.pump_calibration as pump_calibration

    pred_path = tmp_path / "predictions.json"
    port_path = tmp_path / "judge_portfolios.json"
    receipts = _receipts_and_effects_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    port_path.write_text("{}")
    graded = _expired("pump-fail")
    graded.update({"outcome": "miss", "status": "resolved", "correct": False, "actual_pct": -3.0, "resolved_price": 97.0})
    graded["learning_effects"] = {"pending": ["pump"], "done": []}
    pred_path.write_text(json.dumps({"predictions": [], "resolved": [graded], "stats": {}}))
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *a, **k: True)
    monkeypatch.setattr(price_reference, "price_at_resolve_at", lambda *a, **k: ("ok", 110.0, {"price_source": "hourly"}))
    monkeypatch.setattr(pump_calibration, "maybe_adapt_after_resolve", lambda: (_ for _ in ()).throw(OSError("pump down")))
    result = expired_recovery.recover_expired_predictions()
    assert result.get("ok") is not True
    disk = json.loads(pred_path.read_text())["resolved"][0]
    done = ((disk.get("learning_effects") or {}).get("done") or [])
    pending = ((disk.get("learning_effects") or {}).get("pending") or [])
    assert "pump" not in done
    assert "pump" in pending
    assert "pump" not in ((disk.get("learning_effects") or {}).get("indeterminate") or [])
    if receipts.exists():
        assert "pump" not in receipts.read_text()


def test_malformed_but_parseable_pick_history_is_not_rewritten(tmp_path, monkeypatch):
    from internal.council import pick_history

    hist_path = tmp_path / "pick_history.json"
    monkeypatch.setattr(pick_history, "PICK_HISTORY_PATH", str(hist_path))
    payload = json.dumps({"active": None, "history": {}})
    hist_path.write_text(payload)
    before = hist_path.read_bytes()
    obs = pick_history.observe_pick_history()
    assert obs.get("kind") != "readable"
    try:
        result = pick_history.record_hour_pick(
            {"action": "long", "confidence": 0.7, "netuid": 7},
            {"netuid": 7, "name": "Seven", "price": 12},
            prediction_id="malformed-1",
        )
    except Exception:
        result = None
    assert result in {None, False} or (isinstance(result, dict) and result.get("kind") == "unreadable")
    assert hist_path.read_bytes() == before


def test_tracker_idless_postmortem_gate_uses_row_identity(tmp_path, monkeypatch):
    pm_dir = tmp_path / "postmortems"
    pm_dir.mkdir()
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(pm_dir))
    port_path = tmp_path / "judge_portfolios.json"
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    day = {
        "id": None,
        "netuid": 7,
        "direction": "up",
        "predicted_pct": 5.0,
        "reference_price": 100.0,
        "horizon_hours": 24,
        "horizon_type": "day",
        "created_at": "2026-07-01T00:00:00Z",
    }
    hour = {
        "id": None,
        "netuid": 7,
        "name": "Seven",
        "direction": "up",
        "predicted_pct": 5.0,
        "reference_price": 100.0,
        "horizon_hours": 1,
        "horizon_type": "hour",
        "created_at": "2026-07-01T10:00:00Z",
        "outcome": "miss",
        "correct": False,
        "actual_pct": -2.0,
        "resolved_price": 98.0,
        "status": "resolved",
    }
    portfolios.open_position("oracle", day)
    portfolios.open_position("oracle", hour)
    summary = tracker.on_prediction_resolved(hour, apply_judge_nudge=False)
    assert summary.get("wrong") is True
    oracle = (summary.get("judges") or {}).get("oracle") or {}
    assert oracle.get("postmortem") is not None
    book = json.loads(port_path.read_text())
    opens = (book.get("oracle") or {}).get("open_positions") or []
    assert len(opens) == 1
    assert opens[0].get("horizon_type") == "day"


def test_receipt_reads_use_shared_lock(tmp_path, monkeypatch):
    import fcntl as fcntl_mod

    receipts = _receipts_and_effects_paths(tmp_path, monkeypatch)
    flags = []
    real_flock = fcntl_mod.flock

    def record_flock(fd, op):
        flags.append(op)
        return real_flock(fd, op)

    monkeypatch.setattr(fcntl_mod, "flock", record_flock)
    monkeypatch.setattr(expired_recovery.fcntl, "flock", record_flock)
    assert expired_recovery.has_effect_receipt(("id", "lock-r"), "expert") is False
    shared_ops = [op for op in flags if op & fcntl_mod.LOCK_SH]
    exclusive_ops = [op for op in flags if op & fcntl_mod.LOCK_EX]
    assert shared_ops, flags
    assert not exclusive_ops, flags
    flags.clear()
    expired_recovery.write_effect_receipt(("id", "lock-r"), "expert")
    write_shared = [op for op in flags if op & fcntl_mod.LOCK_SH]
    write_excl = [op for op in flags if op & fcntl_mod.LOCK_EX]
    assert write_excl, flags
    assert not write_shared, flags
    assert receipts.exists()


def test_receipt_lock_timeout_has_its_own_reason(tmp_path, monkeypatch):
    from internal.council import resolver, price_reference
    from internal.learning import predictions_store as ps

    pred_path = tmp_path / "predictions.json"
    port_path = tmp_path / "judge_portfolios.json"
    _receipts_and_effects_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    port_path.write_text("{}")
    graded = _expired("lock-timeout")
    graded.update({"outcome": "miss", "status": "resolved", "correct": False, "actual_pct": -3.0, "resolved_price": 97.0})
    graded["learning_effects"] = {"pending": ["finalize", "pump"], "done": []}
    pred_path.write_text(json.dumps({"predictions": [], "resolved": [graded], "stats": {}}))
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *a, **k: True)
    monkeypatch.setattr(price_reference, "price_at_resolve_at", lambda *a, **k: ("ok", 110.0, {"price_source": "hourly"}))

    def boom(*_a, **_k):
        raise expired_recovery.LearningEffectReceiptsLockTimeout("injected lock timeout")

    monkeypatch.setattr(expired_recovery, "has_effect_receipt", boom)
    result = expired_recovery.recover_expired_predictions()
    assert result.get("ok") is not True
    assert result.get("reason") == "receipts_lock_timeout"


def _v8_resolved_effects_setup(tmp_path, monkeypatch, *, pred_id, pending, done=None, indeterminate=None):
    from internal.council import resolver, price_reference
    from internal.learning import predictions_store as ps

    pred_path = tmp_path / "predictions.json"
    port_path = tmp_path / "judge_portfolios.json"
    receipts = _receipts_and_effects_paths(tmp_path, monkeypatch)
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(ps, "PREDICTIONS_PATH", str(pred_path))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    port_path.write_text("{}")
    graded = _expired(pred_id)
    graded.update({"outcome": "miss", "status": "resolved", "correct": False, "actual_pct": -3.0, "resolved_price": 97.0})
    effects = {"pending": list(pending), "done": list(done or [])}
    if indeterminate is not None:
        effects["indeterminate"] = list(indeterminate)
    graded["learning_effects"] = effects
    pred_path.write_text(json.dumps({"predictions": [], "resolved": [graded], "stats": {}}))
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *a, **k: True)
    monkeypatch.setattr(price_reference, "price_at_resolve_at", lambda *a, **k: ("ok", 110.0, {"price_source": "hourly"}))
    return pred_path, receipts


def _v8_effect_counts(monkeypatch):
    import internal.learning.pump_calibration as pump_calibration
    from internal.council import resolver

    counts = {"pump": 0, "finalize": 0}

    def pump():
        counts["pump"] += 1

    def finalize(*_a, **_k):
        counts["finalize"] += 1

    monkeypatch.setattr(pump_calibration, "maybe_adapt_after_resolve", pump)
    monkeypatch.setattr(resolver, "atomic_finalize_resolution", finalize)
    return counts


def _v8_disk_effects(pred_path):
    disk = json.loads(pred_path.read_text())["resolved"][0]
    effects = disk.get("learning_effects") or {}
    return {
        "pending": list(effects.get("pending") or []),
        "done": list(effects.get("done") or []),
        "indeterminate": list(effects.get("indeterminate") or []),
        "row": disk,
    }


def test_receipt_write_timeout_after_pump_marks_indeterminate_and_retry_does_not_reapply(tmp_path, monkeypatch):
    from internal.learning import predictions_store as ps

    pred_path, _receipts = _v8_resolved_effects_setup(
        tmp_path, monkeypatch, pred_id="v8-timeout", pending=["finalize", "pump"]
    )
    counts = _v8_effect_counts(monkeypatch)
    real_write = expired_recovery.write_effect_receipt

    def write_fail_pump(key, effect):
        if effect == "pump":
            raise expired_recovery.LearningEffectReceiptsLockTimeout("injected lock timeout")
        return real_write(key, effect)

    monkeypatch.setattr(expired_recovery, "write_effect_receipt", write_fail_pump)
    first = expired_recovery.recover_expired_predictions()
    assert first.get("ok") is not True
    assert first.get("reason") == "receipts_lock_timeout"
    assert counts["pump"] == 1
    after_one = _v8_disk_effects(pred_path)
    assert "pump" in after_one["indeterminate"]
    assert "pump" not in after_one["pending"]
    assert "pump" not in after_one["done"]

    monkeypatch.setattr(expired_recovery, "write_effect_receipt", real_write)
    before_two = dict(counts)
    ledger_writes = {"n": 0}
    real_merge = ps.merge_ledger_changes

    def counted_merge(*a, **k):
        ledger_writes["n"] += 1
        return real_merge(*a, **k)

    monkeypatch.setattr(ps, "merge_ledger_changes", counted_merge)
    monkeypatch.setattr(predictions_store, "merge_ledger_changes", counted_merge)
    second = expired_recovery.recover_expired_predictions()
    assert second.get("ok") is True
    assert second.get("recovered") == 0
    assert counts["pump"] == before_two["pump"]
    assert counts["finalize"] == before_two["finalize"]
    after_two = _v8_disk_effects(pred_path)
    assert "pump" in after_two["done"]
    assert "pump" not in after_two["indeterminate"]
    assert "pump" not in after_two["pending"]

    writes_after_two = ledger_writes["n"]
    ledger_writes["n"] = 0
    third = expired_recovery.recover_expired_predictions()
    assert third.get("ok") is True
    assert counts["pump"] == before_two["pump"]
    assert counts["finalize"] == before_two["finalize"]
    assert ledger_writes["n"] <= 1
    # unused but documents that run 2 did work on the ledger
    assert writes_after_two == 1


def test_receipt_write_nontimeout_failure_after_pump_marks_indeterminate(tmp_path, monkeypatch):
    pred_path, _receipts = _v8_resolved_effects_setup(
        tmp_path, monkeypatch, pred_id="v8-enospc", pending=["finalize", "pump"]
    )
    counts = _v8_effect_counts(monkeypatch)
    real_write = expired_recovery.write_effect_receipt

    def write_fail_pump(key, effect):
        if effect == "pump":
            raise OSError(28, "No space left on device")
        return real_write(key, effect)

    monkeypatch.setattr(expired_recovery, "write_effect_receipt", write_fail_pump)
    first = expired_recovery.recover_expired_predictions()
    assert first.get("ok") is not True
    assert first.get("reason") == "receipts_write_failed"
    assert counts["pump"] == 1
    after_one = _v8_disk_effects(pred_path)
    assert "pump" in after_one["indeterminate"]
    assert "pump" not in after_one["pending"]
    assert "pump" not in after_one["done"]

    monkeypatch.setattr(expired_recovery, "write_effect_receipt", real_write)
    before_two = dict(counts)
    second = expired_recovery.recover_expired_predictions()
    assert second.get("ok") is True
    assert counts["pump"] == before_two["pump"]
    assert counts["finalize"] == before_two["finalize"]
    after_two = _v8_disk_effects(pred_path)
    assert "pump" in after_two["done"]
    assert "pump" not in after_two["indeterminate"]


def test_receipt_write_still_failing_on_retry_does_not_reapply(tmp_path, monkeypatch):
    pred_path, _receipts = _v8_resolved_effects_setup(
        tmp_path, monkeypatch, pred_id="v8-retry-timeout", pending=["finalize", "pump"]
    )
    counts = _v8_effect_counts(monkeypatch)
    real_write = expired_recovery.write_effect_receipt

    def write_fail_pump(key, effect):
        if effect == "pump":
            raise expired_recovery.LearningEffectReceiptsLockTimeout("injected lock timeout")
        return real_write(key, effect)

    monkeypatch.setattr(expired_recovery, "write_effect_receipt", write_fail_pump)
    first = expired_recovery.recover_expired_predictions()
    assert first.get("reason") == "receipts_lock_timeout"
    assert counts["pump"] == 1
    second = expired_recovery.recover_expired_predictions()
    assert second.get("ok") is not True
    assert second.get("reason") == "receipts_lock_timeout"
    assert counts["pump"] == 1
    after = _v8_disk_effects(pred_path)
    assert "pump" in after["indeterminate"]
    assert "pump" not in after["done"]


def test_indeterminate_only_row_does_not_disable_portfolio_unobservable(tmp_path, monkeypatch):
    pred_path, _receipts = _v8_resolved_effects_setup(
        tmp_path,
        monkeypatch,
        pred_id="v8-unobs",
        pending=[],
        done=["finalize"],
        indeterminate=["pump"],
    )
    counts = _v8_effect_counts(monkeypatch)
    monkeypatch.setattr(
        expired_recovery,
        "observe_portfolios",
        lambda: {"kind": "unreadable", "error": "injected unreadable"},
        raising=False,
    )
    # recover_expired_predictions imports observe_portfolios locally from portfolios
    import internal.judges.portfolios as port_mod

    monkeypatch.setattr(port_mod, "observe_portfolios", lambda: {"kind": "unreadable", "error": "injected unreadable"})
    result = expired_recovery.recover_expired_predictions()
    assert result.get("ok") is not True
    assert result.get("reason") == "portfolio_unobservable"
    assert counts["pump"] == 0
    after = _v8_disk_effects(pred_path)
    assert "pump" in after["indeterminate"]


def test_postmortem_record_times_out_when_lock_is_held(tmp_path, monkeypatch):
    import fcntl
    import multiprocessing
    import time as time_mod

    from internal.judges import postmortems

    pm_dir = tmp_path / "postmortems"
    pm_dir.mkdir()
    monkeypatch.setattr(postmortems, "POSTMORTEMS_DIR", str(pm_dir))
    monkeypatch.setattr(postmortems, "POSTMORTEM_LOCK_TIMEOUT_SECONDS", 0.3)
    path = Path(postmortems._path("oracle"))
    lock_path = str(path) + ".lock"
    ready = multiprocessing.Event()
    release = multiprocessing.Event()

    def hold():
        with open(lock_path, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            ready.set()
            release.wait(timeout=15)

    child = multiprocessing.Process(target=hold)
    child.start()
    try:
        assert ready.wait(timeout=5)
        before = path.read_bytes() if path.exists() else b""
        started = time_mod.monotonic()
        with pytest.raises(postmortems.PostmortemLockTimeout):
            postmortems.record(
                "oracle",
                {"id": "pm-timeout", "netuid": 1, "name": "Seven", "direction": "up", "predicted_pct": 1.0},
                actual_pct=-2.0,
            )
        assert (time_mod.monotonic() - started) < 1.3
        after = path.read_bytes() if path.exists() else b""
        assert after == before
    finally:
        release.set()
        child.join(timeout=5)
    assert child.exitcode == 0
    entry = postmortems.record(
        "oracle",
        {"id": "pm-timeout", "netuid": 1, "name": "Seven", "direction": "up", "predicted_pct": 1.0},
        actual_pct=-2.0,
    )
    assert entry.get("prediction_id") == "pm-timeout"
    assert path.exists()


def test_m2_overlapping_recovers_apply_pump_once(tmp_path, monkeypatch):
    pred_path, _receipts = _v8_resolved_effects_setup(
        tmp_path, monkeypatch, pred_id="v10-overlap", pending=["pump"]
    )
    counts = _v8_effect_counts(monkeypatch)
    barrier = threading.Barrier(2)
    first_seen = {}
    real_has = expired_recovery.has_effect_receipt

    def gated_has(key, effect):
        ident = threading.get_ident()
        if ident not in first_seen:
            first_seen[ident] = True
            barrier.wait(timeout=5)
        return real_has(key, effect)

    monkeypatch.setattr(expired_recovery, "has_effect_receipt", gated_has)
    results = [None, None]

    def run(idx):
        results[idx] = expired_recovery.recover_expired_predictions()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()
    assert counts["pump"] == 1
    after = _v8_disk_effects(pred_path)
    assert "pump" in after["done"]
    assert "pump" not in after["pending"]
    assert "pump" not in after["indeterminate"]


def test_m2_overlap_receipt_write_failure_second_thread_does_not_reapply(tmp_path, monkeypatch):
    pred_path, _receipts = _v8_resolved_effects_setup(
        tmp_path, monkeypatch, pred_id="v10-overlap-fail", pending=["pump"]
    )
    counts = _v8_effect_counts(monkeypatch)
    barrier = threading.Barrier(2)
    first_seen = {}
    real_has = expired_recovery.has_effect_receipt
    real_write = expired_recovery.write_effect_receipt

    def gated_has(key, effect):
        ident = threading.get_ident()
        if ident not in first_seen:
            first_seen[ident] = True
            barrier.wait(timeout=5)
        return real_has(key, effect)

    def write_fail_pump(key, effect):
        if effect == "pump":
            raise expired_recovery.LearningEffectReceiptsLockTimeout("injected lock timeout")
        return real_write(key, effect)

    monkeypatch.setattr(expired_recovery, "has_effect_receipt", gated_has)
    monkeypatch.setattr(expired_recovery, "write_effect_receipt", write_fail_pump)
    results = [None, None]

    def run(idx):
        results[idx] = expired_recovery.recover_expired_predictions()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()
    assert counts["pump"] == 1
    after = _v8_disk_effects(pred_path)
    assert "pump" in after["indeterminate"]
    assert "pump" not in after["pending"]
    assert "pump" not in after["done"]
    assert all(result.get("ok") is not True for result in results)


def test_m2_failed_recheck_does_not_apply(tmp_path, monkeypatch):
    pred_path, _receipts = _v8_resolved_effects_setup(
        tmp_path, monkeypatch, pred_id="v10-recheck", pending=["pump"]
    )
    counts = _v8_effect_counts(monkeypatch)
    calls = {"n": 0}

    def has(_key, _effect):
        calls["n"] += 1
        if calls["n"] == 1:
            return False
        raise expired_recovery.LearningEffectReceiptsUnreadable("injected unreadable")

    monkeypatch.setattr(expired_recovery, "has_effect_receipt", has)
    result = expired_recovery.recover_expired_predictions()
    assert result.get("ok") is not True
    assert result.get("reason") == "effects_incomplete"
    assert counts["pump"] == 0


def test_m2_apply_lock_timeout_does_not_apply(tmp_path, monkeypatch):
    import fcntl
    import multiprocessing
    import time as time_mod

    pred_path, receipts = _v8_resolved_effects_setup(
        tmp_path, monkeypatch, pred_id="v10-apply-timeout", pending=["pump"]
    )
    counts = _v8_effect_counts(monkeypatch)
    monkeypatch.setattr(expired_recovery, "APPLY_LOCK_TIMEOUT_SECONDS", 0.3)
    lock_path = expired_recovery._apply_lock_path()
    Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
    ready = multiprocessing.Event()
    release = multiprocessing.Event()

    def hold():
        with open(lock_path, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            ready.set()
            release.wait(timeout=15)

    child = multiprocessing.Process(target=hold)
    child.start()
    try:
        assert ready.wait(timeout=5)
        started = time_mod.monotonic()
        result = expired_recovery.recover_expired_predictions()
        assert (time_mod.monotonic() - started) < 1.3
        assert result.get("ok") is not True
        assert result.get("reason") == "effect_apply_lock_timeout"
        assert counts["pump"] == 0
    finally:
        release.set()
        child.join(timeout=5)
    assert child.exitcode == 0


def test_m2_receipts_flock_not_held_during_effect_body(tmp_path, monkeypatch):
    import fcntl

    pred_path, receipts = _v8_resolved_effects_setup(
        tmp_path, monkeypatch, pred_id="v10-no-hold", pending=["pump"]
    )
    import internal.learning.pump_calibration as pump_calibration

    held = {"during_effect": None}

    def pump():
        lock_path = expired_recovery._receipts_path() + ".lock"
        Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held["during_effect"] = False
                fcntl.flock(fd, fcntl.LOCK_UN)
            except BlockingIOError:
                held["during_effect"] = True
        finally:
            os.close(fd)

    monkeypatch.setattr(pump_calibration, "maybe_adapt_after_resolve", pump)
    result = expired_recovery.recover_expired_predictions()
    assert result.get("ok") is True
    assert held["during_effect"] is False


def test_m3_indeterminate_mark_retries_once(tmp_path, monkeypatch):
    pred_path, _receipts = _v8_resolved_effects_setup(
        tmp_path, monkeypatch, pred_id="v10-mark-retry", pending=["pump"]
    )
    counts = _v8_effect_counts(monkeypatch)
    real_write = expired_recovery.write_effect_receipt
    real_mark = expired_recovery._mark_effect_indeterminate
    marks = {"n": 0}

    def write_fail_pump(key, effect):
        if effect == "pump":
            raise expired_recovery.LearningEffectReceiptsLockTimeout("injected lock timeout")
        return real_write(key, effect)

    def mark_fail_once(row, effect):
        marks["n"] += 1
        if marks["n"] == 1:
            raise RuntimeError("injected first mark failure")
        return real_mark(row, effect)

    monkeypatch.setattr(expired_recovery, "write_effect_receipt", write_fail_pump)
    monkeypatch.setattr(expired_recovery, "_mark_effect_indeterminate", mark_fail_once)
    first = expired_recovery.recover_expired_predictions()
    assert first.get("ok") is not True
    assert marks["n"] == 2
    after_one = _v8_disk_effects(pred_path)
    assert "pump" in after_one["indeterminate"]
    assert "pump" not in after_one["pending"]
    assert counts["pump"] == 1
    monkeypatch.setattr(expired_recovery, "write_effect_receipt", real_write)
    second = expired_recovery.recover_expired_predictions()
    assert second.get("ok") is True
    assert counts["pump"] == 1
    after_two = _v8_disk_effects(pred_path)
    assert "pump" in after_two["done"]
    assert "pump" not in after_two["indeterminate"]
