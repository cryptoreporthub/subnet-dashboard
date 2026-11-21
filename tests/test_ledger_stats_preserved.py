"""A label-only backfill must leave the stored stats block as it was.

Base wrote the ledger without touching stats. Head's merge recomputed stats from the
default function, which dropped the expired, council_pending and pump_pending keys
and counted pump rows as council pending.
"""

from __future__ import annotations

import json

from internal.learning import expert_backfill, predictions_store


def test_backfill_keeps_stored_stats(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stored_stats = {
        "correct": 0, "wrong": 0, "expired": 1, "pending": 0,
        "council_pending": 0, "pump_pending": 1, "total": 1, "accuracy": 0.0,
    }
    path = tmp_path / "predictions.json"
    path.write_text(json.dumps({
        "predictions": [{"id": "p1", "netuid": 1, "status": "pending", "horizon_type": "hour",
                         "created_at": "2026-01-01T00:00:00Z"}],
        "resolved": [{"id": "e1", "netuid": 2, "status": "expired", "outcome": "expired",
                      "horizon_type": "hour", "created_at": "2026-01-01T00:00:00Z"}],
        "stats": stored_stats,
    }))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))
    monkeypatch.setattr(expert_backfill, "resolve_expert_attribution", lambda row: ("quant", "existing"))

    out = expert_backfill.backfill_expert_attribution(dry_run=False)

    assert out.get("ok") is not False, out
    assert json.loads(path.read_text())["stats"] == stored_stats


def test_backfill_relabel_keeps_row_order(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    resolved = [
        {"id": f"r{i}", "netuid": i, "status": "correct", "outcome": "correct",
         "horizon_type": "hour", "created_at": "2026-01-01T00:00:00Z",
         "expert": "" if i <= 2 else "quant"}
        for i in range(1, 6)
    ]
    path = tmp_path / "predictions.json"
    path.write_text(json.dumps({"predictions": [], "resolved": resolved, "stats": {}}))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))
    monkeypatch.setattr(expert_backfill, "resolve_expert_attribution", lambda row: ("quant", "existing"))

    out = expert_backfill.backfill_expert_attribution(dry_run=False)

    assert out["updated"] == 2, out
    rows = json.loads(path.read_text())["resolved"]
    assert [r["id"] for r in rows] == ["r1", "r2", "r3", "r4", "r5"]
    assert [r["expert"] for r in rows[:2]] == ["quant", "quant"]



def test_backfill_refused_write_is_http_error(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from server import app

    monkeypatch.chdir(tmp_path)
    path = tmp_path / "predictions.json"
    path.write_text(json.dumps({
        "predictions": [],
        "resolved": [{"id": "r1", "netuid": 1, "status": "correct", "outcome": "correct",
                      "horizon_type": "hour", "created_at": "2026-01-01T00:00:00Z"}],
        "stats": {},
    }))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))
    monkeypatch.setattr(expert_backfill, "resolve_expert_attribution", lambda row: ("quant", "existing"))
    monkeypatch.setattr(
        expert_backfill, "merge_ledger_changes",
        lambda *a, **k: predictions_store.PersistResult(
            predictions_store.PersistOutcome.REFUSED, predictions_store.PersistReason.CONFLICT_ONLY,
        ),
    )

    response = TestClient(app).post("/api/learning/backfill-expert-attribution?dry_run=false")

    assert response.status_code == 500, (response.status_code, response.text)
