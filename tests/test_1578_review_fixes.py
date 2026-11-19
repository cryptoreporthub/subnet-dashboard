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
