"""N3 calibration scheduler hook tests."""

from __future__ import annotations

import json

import pytest

from internal.calibration import pipeline as cal
from internal.calibration import scheduler as sched


def _resolved_row(expert: str, correct: bool, *, idx: int = 0) -> dict:
    actual = 2.0 if correct else -2.0
    return {
        "id": f"p-{idx}",
        "expert": expert,
        "netuid": idx + 1,
        "status": "resolved",
        "outcome": "hit" if correct else "miss",
        "correct": correct,
        "actual_pct": actual,
        "predicted_pct": 1.0,
        "direction": "up",
        "reference_price": 100.0,
        "resolved_price": 100.0 + actual,
        "created_at": f"2026-07-02T12:{idx:02d}:00Z",
        "resolved_at": f"2026-07-02T13:{idx:02d}:00Z",
    }


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    soul = tmp_path / "soul_map.json"
    pred = tmp_path / "predictions.json"
    soul.write_text(
        json.dumps(
            {"adversarial_state": {"calibration": {"last_retrain_at": "2026-01-01T00:00:00Z"}}}
        ),
        encoding="utf-8",
    )
    pred.write_text(json.dumps({"predictions": [], "resolved": [], "stats": {}}), encoding="utf-8")
    monkeypatch.setattr(cal, "PREDICTIONS_PATH", str(pred))
    monkeypatch.setattr("internal.council.resolver.PREDICTIONS_PATH", str(pred))
    monkeypatch.setenv("SOUL_MAP_PATH", str(soul))
    monkeypatch.delenv("CALIBRATION_AUTO_RETRAIN", raising=False)
    yield {"soul": str(soul), "pred": str(pred)}


def test_auto_retrain_disabled_by_default(isolate):
    result = sched.maybe_trigger_auto_retrain(resolved_now=5)
    assert result["triggered"] is False
    assert result["reason"] == "disabled"


def test_auto_retrain_insufficient_sample(isolate, monkeypatch):
    monkeypatch.setenv("CALIBRATION_AUTO_RETRAIN", "on")
    result = sched.maybe_trigger_auto_retrain()
    assert result["triggered"] is False
    assert result["reason"] == "insufficient_total_sample"


def test_auto_retrain_triggers_when_threshold_met(isolate, monkeypatch):
    monkeypatch.setenv("CALIBRATION_AUTO_RETRAIN", "on")
    rows = [_resolved_row("quant", True, idx=i) for i in range(35)]
    with open(isolate["pred"], "w", encoding="utf-8") as fh:
        json.dump({"predictions": [], "resolved": rows, "stats": {}}, fh)

    started = []

    def fake_start(**kwargs):
        started.append(kwargs)
        return {"started": True, "in_progress": True}

    monkeypatch.setattr(sched, "start_retrain_async", fake_start)
    result = sched.maybe_trigger_auto_retrain(resolved_now=3)
    assert result["triggered"] is True
    assert result["reason"] == "started"
    assert len(started) == 1
