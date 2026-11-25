"""Adversary repro: real concurrent-writer conflict during expire (no stubbed commit)."""
import json

from internal.council import resolver


def _row(pid):
    return {"id": pid, "status": "pending", "netuid": 1, "direction": "up",
            "predicted_pct": 5.0, "reference_price": 1.0, "horizon_hours": 1,
            "resolve_at": "2000-01-01T00:00:00Z", "resolve_attempts": 99}


def test_conflicted_expiry_reports_disk_stats(tmp_path, monkeypatch):
    ledger = tmp_path / "predictions.json"
    ledger.write_text(json.dumps({"predictions": [_row("p1"), _row("p2")], "resolved": [],
                                  "stats": {"correct": 0, "wrong": 0, "pending": 2}}))
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(ledger))
    real_watchdog = resolver.check_resolver_watchdog

    def concurrent_writer(*a, **k):
        # Another writer touches p1 on disk after expire loaded the ledger.
        disk = json.loads(ledger.read_text())
        disk["predictions"][0]["note"] = "touched by another writer"
        ledger.write_text(json.dumps(disk))
        return real_watchdog(*a, **k)

    monkeypatch.setattr(resolver, "check_resolver_watchdog", concurrent_writer)
    out = resolver.expire_stale_predictions()
    disk = json.loads(ledger.read_text())
    assert [r["id"] for r in out["expired_now"]] == ["p2"]
    assert out["stats"]["pending"] == 1, "p1 is conflicted, so it is still pending"
    assert disk["stats"]["pending"] == 1
    assert out["stats"]["pending"] == disk["stats"]["pending"]
