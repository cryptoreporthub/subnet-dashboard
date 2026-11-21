"""A row whose expiry write conflicted is not reported as expired."""

import json
from types import SimpleNamespace

from internal.council import resolver


def test_conflicted_expiry_is_not_reported(tmp_path, monkeypatch):
    ledger = tmp_path / "predictions.json"
    ledger.write_text(json.dumps({
        "predictions": [{"id": "p1", "status": "pending", "netuid": 1, "resolve_at": "2000-01-01T00:00:00Z", "resolve_attempts": 99}],
        "resolved": [],
        "stats": {"correct": 0, "wrong": 0, "pending": 1},
    }))
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(ledger))
    monkeypatch.setattr(
        resolver, "_commit_ledger_changes",
        lambda *_a, **_k: SimpleNamespace(conflicts=["p1"], committed_keys=[]),
    )
    out = resolver.expire_stale_predictions()
    assert out["expired_now"] == []
