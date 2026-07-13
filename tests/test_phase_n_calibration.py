"""Phase N — calibration / retrain tests."""

from __future__ import annotations

import json

import pytest

from internal.calibration import pipeline as cal


def _write_predictions(path, resolved):
    path.write_text(
        json.dumps({"predictions": [], "resolved": resolved, "stats": {}}),
        encoding="utf-8",
    )


def _resolved_row(expert: str, correct: bool, *, idx: int = 0) -> dict:
    actual = 2.0 if correct else -2.0
    direction = "up" if correct else "up"  # wrong = predicted up, actual down
    return {
        "id": f"p-{idx}",
        "expert": expert,
        "status": "resolved",
        "outcome": "hit" if correct else "miss",
        "correct": correct,
        "actual_pct": actual,
        "predicted_pct": 1.0,
        "direction": direction,
        "reference_price": 100.0,
        "resolved_price": 100.0 + actual,
        "created_at": f"2026-07-01T12:{idx:02d}:00Z",
        "resolved_at": f"2026-07-01T13:{idx:02d}:00Z",
    }


@pytest.fixture(autouse=True)
def isolate_paths(tmp_path, monkeypatch):
    soul_path = str(tmp_path / "soul_map.json")
    pred_path = str(tmp_path / "predictions.json")
    (tmp_path / "soul_map.json").write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "council_weights": {
                        "quant": 1.0,
                        "hype": 1.0,
                        "dark_horse": 1.0,
                        "technical": 1.0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    _write_predictions(tmp_path / "predictions.json", [])
    monkeypatch.setattr(cal, "PREDICTIONS_PATH", pred_path)
    monkeypatch.setattr("internal.council.resolver.PREDICTIONS_PATH", pred_path)
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", soul_path)
    yield {"soul": soul_path, "pred": pred_path}


def test_compute_proposed_weights_respects_floor_and_ceiling(isolate_paths):
    rows = [_resolved_row("quant", True, idx=i) for i in range(40)]
    proposed = cal.compute_proposed_weights(rows)
    assert all(cal.WEIGHT_FLOOR <= v <= cal.WEIGHT_CEILING for v in proposed.values())
    assert proposed["quant"] > proposed["hype"]


def test_cert_fails_insufficient_sample(isolate_paths):
    rows = [_resolved_row("quant", True, idx=i) for i in range(5)]
    proposed = cal.compute_proposed_weights(rows)
    cert = cal.certify_weights(proposed, rows)
    assert cert["passed"] is False
    assert cert["reason"] == "insufficient_data"


def test_cert_fails_when_proposed_worse_than_current(isolate_paths):
    rows = [_resolved_row("quant", True, idx=i) for i in range(20)]
    rows += [_resolved_row("hype", False, idx=i + 100) for i in range(15)]
    current = {"quant": 1.4, "hype": 0.7, "dark_horse": 1.0, "technical": 1.0}
    proposed = {"quant": 0.7, "hype": 1.4, "dark_horse": 1.0, "technical": 1.0}
    cert = cal.certify_weights(proposed, rows, current=current)
    assert cert["passed"] is False
    assert cert["reason"] == "accuracy_regression"


def test_cert_passes_when_proposed_better(isolate_paths):
    rows = [_resolved_row("quant", True, idx=i) for i in range(35)]
    rows += [_resolved_row("hype", False, idx=i + 100) for i in range(10)]
    proposed = cal.compute_proposed_weights(rows)
    current = {k: 1.0 for k in proposed}
    cert = cal.certify_weights(proposed, rows, current=current)
    assert cert["passed"] is True


def test_dedupe_rows_excluded_from_training(isolate_paths):
    pred_path = isolate_paths["pred"]
    dup = _resolved_row("quant", True, idx=1)
    dup2 = dict(dup)
    dup2["id"] = "dup-2"
    dup2["status"] = "duplicate"
    dup2["outcome"] = "duplicate"
    dup2["correct"] = None
    from pathlib import Path

    _write_predictions(Path(pred_path), [dup2])
    rows = cal.load_training_rows(pred_path)
    assert len(rows) == 0


def test_dry_run_never_writes_weights(isolate_paths):
    from pathlib import Path

    pred_path = isolate_paths["pred"]
    _write_predictions(
        Path(pred_path),
        [_resolved_row("quant", True, idx=i) for i in range(35)],
    )
    from internal.council.weights import load_weights

    before = dict(load_weights(isolate_paths["soul"]))
    result = cal.run_calibration_pipeline(
        dry_run=True,
        soul_map_path=isolate_paths["soul"],
        predictions_path=pred_path,
    )
    after = dict(load_weights(isolate_paths["soul"]))
    assert result["status"] == "dry_run"
    assert before == after


def test_fire_atomic_swap(isolate_paths):
    pred_path = isolate_paths["pred"]
    from pathlib import Path

    _write_predictions(
        Path(pred_path),
        [_resolved_row("quant", True, idx=i) for i in range(35)],
    )
    proposed = {"quant": 1.5, "hype": 0.8, "dark_horse": 0.9, "technical": 1.0}
    fired = cal.fire_weights(proposed, soul_map_path=isolate_paths["soul"])
    assert fired["quant"] == pytest.approx(1.5, abs=1e-4)


def test_fire_rollback_on_verify_fail(isolate_paths, monkeypatch):
    proposed = {"quant": 1.5, "hype": 0.8, "dark_horse": 0.9, "technical": 1.0}
    from internal.council import weights as w

    real_load = w.load_weights

    calls = {"n": 0}

    def flaky_load(path=w.SOUL_MAP_PATH):
        calls["n"] += 1
        data = real_load(path)
        if calls["n"] == 2:
            data = dict(data)
            data["quant"] = 9.9
        return data

    monkeypatch.setattr(cal, "load_weights", flaky_load)
    with pytest.raises(cal.FireError):
        cal.fire_weights(proposed, soul_map_path=isolate_paths["soul"])
    restored = real_load(isolate_paths["soul"])
    assert restored["quant"] == pytest.approx(1.0, abs=1e-4)


def test_status_endpoint_shape():
    from fastapi.testclient import TestClient
    from server import app

    client = TestClient(app)
    resp = client.get("/api/calibration/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "weights" in body
    assert "calibration" in body
    assert "thresholds" in body


def test_retrain_dry_run_endpoint():
    from fastapi.testclient import TestClient
    from server import app

    client = TestClient(app)
    resp = client.post("/api/calibration/retrain", json={"dry_run": True, "async": False})
    assert resp.status_code == 200
    assert resp.json()["status"] in {"dry_run", "cert_failed"}
