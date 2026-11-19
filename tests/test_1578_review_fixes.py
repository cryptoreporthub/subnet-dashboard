"""Regression tests for the #1578 review fixes (r4 pick id, F1 persist outcome)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

import internal.council.resolver_scheduler as resolver_scheduler
from internal.learning import predictions_store
from internal.learning.prediction_loop import PickRecordKind, record_pick
from internal.learning.pump_lead_ledger import record_pump_lead_at_phase_entry
from internal.store.soul_map_io import WriteOutcome
from internal.council import resolver
from internal.council.weights import load_weights, save_weights
from internal.judges.weights import load_judge_weights, nudge_judge, save_judge_weights


@pytest.fixture
def predictions_file(tmp_path: Path) -> str:
    path = str(tmp_path / "predictions.json")
    Path(path).write_text(
        json.dumps(predictions_store._default_data()), encoding="utf-8"
    )
    return path


def test_record_pick_keeps_preattached_id_when_statement_is_rebuilt(predictions_file):
    """r4: a pre-attached prediction without a statement keeps its id on the stored row."""
    pick = {
        "prediction": {
            "id": "pick-id-123",
            "predicted_pct": 2.5,
            "horizon_hours": 1,
        },
    }
    subnet = {"netuid": 7, "price": 1.0, "name": "sn7"}

    record = record_pick(
        pick, subnet, horizon_type="hour", predictions_path=predictions_file
    )

    assert record.kind is PickRecordKind.COMMITTED
    assert record.prediction["id"] == "pick-id-123"
    stored = json.loads(Path(predictions_file).read_text(encoding="utf-8"))
    assert [row["id"] for row in stored["predictions"]] == ["pick-id-123"]


def test_record_pick_refuses_a_preattached_id_already_owned_by_another_row(predictions_file):
    """Replit r4 follow-up: a kept id must not duplicate an id already in the ledger."""
    Path(predictions_file).write_text(
        json.dumps(
            {
                **predictions_store._default_data(),
                "predictions": [
                    {"id": "reused-id", "netuid": 8, "horizon_type": "hour",
                     "status": "pending", "shadow": False}
                ],
            }
        ),
        encoding="utf-8",
    )
    pick = {
        "prediction": {"id": "reused-id", "predicted_pct": 2.5, "horizon_hours": 1},
    }
    subnet = {"netuid": 7, "price": 1.0, "name": "sn7"}

    record = record_pick(
        pick, subnet, horizon_type="hour", predictions_path=predictions_file
    )

    assert record.kind is not PickRecordKind.COMMITTED
    stored = json.loads(Path(predictions_file).read_text(encoding="utf-8"))
    assert [row["id"] for row in stored["predictions"]] == ["reused-id"]
    assert [row["netuid"] for row in stored["predictions"]] == [8]


def test_persist_lifecycle_non_storage_exception_is_persist_error(
    tmp_path, monkeypatch
):
    """F1: a non-storage exception from the persist path is not typed as replace_failed."""
    soul_path = tmp_path / "soul_map.json"
    soul_path.write_text("{}", encoding="utf-8")
    sched = resolver_scheduler.PredictionResolverScheduler(
        refresh_minutes=1, soul_map_path=str(soul_path)
    )

    def _boom(*args, **kwargs):
        raise TypeError("caller bug, not a storage failure")

    monkeypatch.setattr(resolver_scheduler, "write_soul_map", _boom)

    result = sched._persist_lifecycle_state()

    assert result.outcome is WriteOutcome.PERSIST_ERROR
    assert result.outcome is not WriteOutcome.REPLACE_FAILED
    assert "TypeError" in result.detail


def test_one_bad_pick_does_not_stop_reconciling_the_rest(tmp_path, monkeypatch):
    """A row whose position open raises must not abort the reconcile sweep for later picks."""
    import json as _json
    from datetime import datetime as _dt, timezone as _tz

    from internal.judges import portfolios
    from internal.learning import prediction_loop

    now = _dt.now(_tz.utc).isoformat().replace("+00:00", "Z")
    ledger = tmp_path / "predictions.json"
    base = {"pick_source": "council", "status": "pending", "created_at": now,
            "judge_scores_at_creation": {"oracle": {}}}
    ledger.write_text(_json.dumps({
        "predictions": [dict(base, id="bad-1"), dict(base, id="good-2")],
        "resolved": [], "stats": {},
    }))
    port = tmp_path / "judge_portfolios.json"
    port.write_text("{}")
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port))

    opened = []

    def open_positions(row, scores):
        if row["id"] == "bad-1":
            raise RuntimeError("corrupt pick")
        opened.append(row["id"])

    monkeypatch.setattr(portfolios, "open_positions_for_prediction", open_positions)
    count = prediction_loop.reconcile_judge_positions(predictions_path=str(ledger))

    assert opened == ["good-2"], f"later pick was never reconciled: {opened}"
    assert count == 1


@pytest.fixture
def soul(tmp_path, monkeypatch):
    path = str(tmp_path / "soul_map.json")
    save_weights({"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}, path)
    save_judge_weights({"oracle": 1.0, "echo": 1.0, "pulse": 1.0}, path)
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", path)
    monkeypatch.setattr("internal.judges.weights.SOUL_MAP_PATH", path)
    return path


@pytest.fixture
def trail_down(monkeypatch):
    def _raise(*_a, **_k):
        raise RuntimeError("trail unavailable")

    monkeypatch.setattr("internal.learning.trail_bus.emit_weight_change", _raise)


def _error_records(caplog, marker: str):
    return [
        r
        for r in caplog.records
        if r.levelno >= logging.ERROR and marker in r.getMessage()
    ]


def test_expert_nudge_keeps_write_and_logs_failed_emit(soul, trail_down, caplog):
    """A failed weight-change trail emit keeps the expert write and logs an ERROR."""
    with caplog.at_level(logging.ERROR):
        resolver._nudge_weights(True, "quant")

    assert load_weights(soul)["quant"] > 1.0
    assert _error_records(caplog, "emit_weight_change"), "emit failure was swallowed silently"


def test_judge_nudge_keeps_write_and_logs_failed_emit(soul, trail_down, caplog):
    """A failed trail emit keeps the judge write and logs an ERROR."""
    with caplog.at_level(logging.ERROR):
        after = nudge_judge("oracle", True, soul)

    assert after is not None and after > 1.0
    assert load_judge_weights(soul)["oracle"] == pytest.approx(after, abs=1e-4)
    assert _error_records(caplog, "emit_weight_change"), "emit failure was swallowed silently"


def test_judge_audit_nudge_keeps_write_and_logs_failed_emit(soul, trail_down, caplog):
    """A failed trail emit keeps the audit-driven expert writes and logs an ERROR."""
    prediction = {"judge_scores_at_creation": {"oracle": 0.9, "echo": 0.1, "pulse": 0.1}}
    with caplog.at_level(logging.ERROR):
        resolver._nudge_weights_from_judge_audit(prediction, True)

    assert any(v != 1.0 for v in load_weights(soul).values()), "audit nudge was not persisted"
    assert _error_records(caplog, "emit_weight_change"), "emit failure was swallowed silently"


def test_refused_pump_lead_append_returns_none_and_logs_warning(predictions_file, monkeypatch, caplog):
    """I1: a refused ledger append is reported as a warning, not dropped at debug level."""
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", predictions_file)
    Path(predictions_file).write_text("{not json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        row = record_pump_lead_at_phase_entry(
            netuid=28,
            name="LOL",
            phase="ACCUMULATING",
            composite_score=0.62,
            reference_price=0.05,
            signal_snapshot={"buy_ratio": 0.7, "volume_intensity": 0.4, "price": 0.05},
        )

    assert row is None
    assert Path(predictions_file).read_text(encoding="utf-8") == "{not json"
    assert any(
        r.levelno == logging.WARNING and "pump_lead" in r.getMessage() for r in caplog.records
    ), "refused pump lead row was dropped without a warning"


def test_calibration_state_save_keeps_concurrent_signal_weights_write(tmp_path, monkeypatch):
    from internal.calibration import pipeline as calibration_pipeline
    from internal.store import soul_map_io

    soul = str(tmp_path / "soul_map.json")
    real_write = soul_map_io.write_soul_map
    real_write(lambda blob: blob.update({"seed": 1}), soul)

    concurrent_writes = []

    def interleaving_write(mutator, path=None, **kwargs):
        # A second writer lands between the calibration save's read and its write.
        if not concurrent_writes:
            concurrent_writes.append("signal_weights")
            real_write(lambda blob: blob.update({"signal_weights": {"hour": 1.5}}), path)
        return real_write(mutator, path, **kwargs)

    monkeypatch.setattr(soul_map_io, "write_soul_map", interleaving_write)
    persisted = calibration_pipeline._save_calibration_state(
        {"last_retrain_at": "2026-11-19T00:00:00Z"},
        soul_map_path=soul,
    )

    assert concurrent_writes == ["signal_weights"], "interleaving never happened"
    blob = json.loads(Path(soul).read_text(encoding="utf-8"))
    assert blob["signal_weights"] == {"hour": 1.5}
    assert blob["adversarial_state"]["calibration"]["last_retrain_at"] == "2026-11-19T00:00:00Z"


def test_calibration_state_save_reports_persisted_when_write_applies(tmp_path):
    from internal.calibration import pipeline as calibration_pipeline

    soul = str(tmp_path / "soul_map.json")
    persisted = calibration_pipeline._save_calibration_state(
        {"last_retrain_at": "2026-11-19T00:00:00Z"},
        soul_map_path=soul,
    )

    assert persisted is True


@pytest.mark.parametrize(
    ("force", "expected_status"),
    [(False, "cert_failed"), (True, "fired")],
)
def test_refused_calibration_state_write_is_reported_not_raised(
    tmp_path, monkeypatch, caplog, force, expected_status
):
    from internal.calibration import pipeline as calibration_pipeline
    from internal.store import soul_map_io

    soul = str(tmp_path / "soul_map.json")
    predictions = str(tmp_path / "predictions.json")

    def refusing_write(mutator, path=None, **kwargs):
        return soul_map_io.WriteResult(WriteOutcome.REPLACE_FAILED, None, detail="injected")

    monkeypatch.setattr(soul_map_io, "write_soul_map", refusing_write)
    monkeypatch.setattr(
        calibration_pipeline,
        "fire_weights",
        lambda proposed, **kwargs: dict(proposed),
    )
    with caplog.at_level(logging.WARNING):
        result = calibration_pipeline.run_calibration_pipeline(
            force=force,
            soul_map_path=soul,
            predictions_path=predictions,
        )

    assert result["status"] == expected_status
    assert result["state_persisted"] is False
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("calibration state" in msg and "refused" in msg for msg in warnings), warnings


def test_fire_error_with_refused_state_write_returns_fire_failed(tmp_path, monkeypatch):
    from internal.calibration import pipeline as calibration_pipeline
    from internal.store import soul_map_io

    soul = str(tmp_path / "soul_map.json")
    predictions = str(tmp_path / "predictions.json")

    def refusing_write(mutator, path=None, **kwargs):
        return soul_map_io.WriteResult(WriteOutcome.REPLACE_FAILED, None, detail="injected")

    def failing_fire(proposed, **kwargs):
        raise calibration_pipeline.FireError("injected fire failure")

    monkeypatch.setattr(soul_map_io, "write_soul_map", refusing_write)
    monkeypatch.setattr(calibration_pipeline, "fire_weights", failing_fire)
    result = calibration_pipeline.run_calibration_pipeline(
        force=True,
        soul_map_path=soul,
        predictions_path=predictions,
    )

    assert result["status"] == "fire_failed"
    assert result["state_persisted"] is False


def test_refused_combined_exp_append_returns_no_id_and_logs_warning(
    predictions_file, tmp_path, monkeypatch, caplog
):
    """Combined-exp I1 sibling: a refused ledger append is a logged warning, not a debug line."""
    from internal.pump import combined_ledger

    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", predictions_file)
    monkeypatch.setattr(combined_ledger, "LEDGER_PATH", str(tmp_path / "combined_calls.json"))
    Path(predictions_file).write_text("{not json", encoding="utf-8")
    angles = {
        "focus_netuid": 23,
        "weights": {"timing": 0.7, "peer": 0.3},
        "combined": {
            "netuid": 11,
            "name": "Sub11",
            "timing_pts": 80,
            "peer_pts": 40,
            "combined_pts": 68,
            "price": 1.2,
            "phase": "ACCUMULATING",
            "score": 0.6,
        },
        "tracked": [{"netuid": 11, "combined_pts": 68}],
    }

    with caplog.at_level(logging.WARNING):
        call = combined_ledger.maybe_record_combined_call(angles)

    assert call is not None
    assert call["prediction_id"] is None
    assert Path(predictions_file).read_text(encoding="utf-8") == "{not json"
    assert any(
        r.levelno == logging.WARNING and "combined" in r.getMessage() for r in caplog.records
    ), "refused combined-exp row was dropped without a warning"


def test_combined_exp_locked_duplicate_returns_no_id_and_writes_nothing(
    predictions_file, tmp_path, monkeypatch
):
    """A pending combined-exp row that lands after the pre-check, inside the locked append,
    must not yield a prediction_id for a row that was never written."""
    from internal.pump import combined_ledger

    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", predictions_file)
    monkeypatch.setattr(combined_ledger, "LEDGER_PATH", str(tmp_path / "combined_calls.json"))
    real_append = predictions_store.append_prediction_result
    landed = []

    def competing_then_append(prediction, **kwargs):
        if not landed:
            landed.append("competing")
            real_append(
                {
                    "id": "competing-row",
                    "netuid": 11,
                    "name": "Sub11",
                    "direction": "up",
                    "predicted_pct": 2.0,
                    "horizon_hours": 1,
                    "horizon_type": "pump_combined_exp",
                    "reference_price": 1.2,
                    "created_at": "2026-11-19T00:00:00Z",
                    "resolve_at": "2026-11-19T01:00:00Z",
                    "status": "pending",
                    "shadow": False,
                    "pick_source": "pump_combined_exp",
                }
            )
        return real_append(prediction, **kwargs)

    monkeypatch.setattr(predictions_store, "append_prediction_result", competing_then_append)
    angles = {
        "focus_netuid": 23,
        "weights": {"timing": 0.7, "peer": 0.3},
        "combined": {
            "netuid": 11,
            "name": "Sub11",
            "timing_pts": 80,
            "peer_pts": 40,
            "combined_pts": 68,
            "price": 1.2,
            "phase": "ACCUMULATING",
            "score": 0.6,
        },
        "tracked": [{"netuid": 11, "combined_pts": 68}],
    }

    call = combined_ledger.maybe_record_combined_call(angles)

    assert landed == ["competing"], "the competing row never landed inside the locked append"
    assert call is not None
    assert call["prediction_id"] is None
    stored = json.loads(Path(predictions_file).read_text(encoding="utf-8"))
    assert [row["id"] for row in stored["predictions"]] == ["competing-row"]


def test_pump_lead_locked_duplicate_returns_none_and_writes_nothing(predictions_file, monkeypatch):
    """A pending pump_lead row that lands after the pre-check must not yield a returned lead."""
    from internal.learning import pump_lead_ledger

    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", predictions_file)
    real_append = predictions_store.append_prediction_result
    landed = []

    def competing_then_append(prediction, **kwargs):
        if not landed:
            landed.append("competing")
            real_append(
                {
                    "id": "competing-row",
                    "netuid": 11,
                    "name": "Sub11",
                    "direction": "up",
                    "predicted_pct": 2.0,
                    "horizon_hours": 1,
                    "horizon_type": "pump_lead",
                    "reference_price": 1.2,
                    "created_at": "2026-11-19T00:00:00Z",
                    "resolve_at": "2026-11-19T01:00:00Z",
                    "status": "pending",
                    "shadow": False,
                    "pick_source": "pump_lead",
                }
            )
        return real_append(prediction, **kwargs)

    monkeypatch.setattr(pump_lead_ledger, "append_prediction_result", competing_then_append)

    result = pump_lead_ledger.record_pump_lead_at_phase_entry(
        netuid=11,
        name="Sub11",
        phase="ACCUMULATING",
        composite_score=0.6,
        reference_price=1.2,
        signal_snapshot={"buy_ratio": 0.8, "volume_intensity": 2.0},
    )

    assert landed == ["competing"], "the competing row never landed inside the locked append"
    assert result is None
    stored = json.loads(Path(predictions_file).read_text(encoding="utf-8"))
    assert [row["id"] for row in stored["predictions"]] == ["competing-row"]


# U6 (I8): both hour-pick sites decide "is this row committed" the same way. A pick
# reaches pick history only when its ledger row was committed. Each case below is
# driven through the public site function, and the assertion is whether the
# prediction id lands in pick history.
_PICK_SITE_PICK = {"action": "long", "subnet": {"netuid": 7, "price": 12}}
_PICK_SITE_SUBNETS = [{"netuid": 7, "price": 12, "name": "SN7"}]
_PICK_SITE_CASES = [
    pytest.param(
        PickRecordKind.COMMITTED, {"id": "p-committed"}, None, True, id="committed"
    ),
    pytest.param(
        PickRecordKind.INDETERMINATE,
        {"id": "p-incomplete"},
        "positions_incomplete",
        True,
        id="committed-positions-incomplete",
    ),
    pytest.param(
        PickRecordKind.INDETERMINATE,
        {"id": "p-filed"},
        "ledger_indeterminate",
        False,
        id="filed-but-never-written",
    ),
    pytest.param(PickRecordKind.SKIPPED, None, "duplicate", False, id="duplicate"),
]


@pytest.fixture
def pick_site_history(tmp_path, monkeypatch):
    from internal.council import pick_history

    path = tmp_path / "pick_history.json"
    path.write_text(json.dumps({"active": None, "history": []}), encoding="utf-8")
    monkeypatch.setattr(pick_history, "PICK_HISTORY_PATH", str(path))
    monkeypatch.setattr(predictions_store, "pending_hour_prediction", lambda netuid: None)
    return pick_history


@pytest.mark.parametrize("kind, prediction, reason, expected_recorded", _PICK_SITE_CASES)
def test_scheduler_site_records_pick_history_only_for_committed_rows(
    pick_site_history, monkeypatch, kind, prediction, reason, expected_recorded
):
    import internal.council.pick_scheduler as pick_scheduler
    from internal.learning import prediction_loop

    monkeypatch.setattr(pick_scheduler, "_load_subnets", lambda: _PICK_SITE_SUBNETS)
    monkeypatch.setattr(
        prediction_loop,
        "record_pick",
        lambda *a, **k: prediction_loop.PickRecord(kind, prediction, reason),
    )
    pick_scheduler._record_hour_pick(_PICK_SITE_PICK, _PICK_SITE_SUBNETS, {})
    recorded = expected_recorded and prediction is not None
    assert pick_site_history.has_prediction(prediction["id"] if prediction else "") is recorded


@pytest.mark.parametrize("kind, prediction, reason, expected_recorded", _PICK_SITE_CASES)
def test_server_site_records_pick_history_only_for_committed_rows(
    pick_site_history, monkeypatch, kind, prediction, reason, expected_recorded
):
    import server
    from internal.learning import prediction_loop

    monkeypatch.setattr(
        prediction_loop,
        "record_pick",
        lambda *a, **k: prediction_loop.PickRecord(kind, prediction, reason),
    )
    server._record_pick_in_learning_loop(
        _PICK_SITE_PICK, _PICK_SITE_SUBNETS, {}, "hour"
    )
    recorded = expected_recorded and prediction is not None
    assert pick_site_history.has_prediction(prediction["id"] if prediction else "") is recorded


def test_signal_nudge_keeps_write_and_logs_failed_emit(soul, trail_down, caplog):
    """A failed weight-change trail emit keeps the signal write and logs an ERROR."""
    from internal.council.weights import nudge_signal_weight

    with caplog.at_level(logging.ERROR):
        new_val = nudge_signal_weight("hour", "quant", True, path=soul)

    assert new_val is not None and new_val > 1.0, "signal write was not applied"
    assert _error_records(caplog, "emit_weight_change"), "emit failure was swallowed silently"
