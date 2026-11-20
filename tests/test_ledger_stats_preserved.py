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
