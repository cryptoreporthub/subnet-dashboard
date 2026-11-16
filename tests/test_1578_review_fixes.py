"""Regression tests for the #1578 review fixes (r4 pick id, F1 persist outcome)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import internal.council.resolver_scheduler as resolver_scheduler
from internal.learning import predictions_store
from internal.learning.prediction_loop import PickRecordKind, record_pick
from internal.store.soul_map_io import WriteOutcome


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
