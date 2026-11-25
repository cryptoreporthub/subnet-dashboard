"""A conflicted ledger commit must return the committed snapshot, not a mix of
memory and a later disk read."""
import json

import pytest

from internal.council import resolver


def _row(pid):
    return {"id": pid, "status": "pending", "netuid": 1, "direction": "up",
            "predicted_pct": 5.0, "reference_price": 1.0, "horizon_hours": 1,
            "resolve_at": "2000-01-01T00:00:00Z", "resolve_attempts": 99}


@pytest.fixture
def conflicted_ledger(tmp_path, monkeypatch):
    """Ledger of p1,p2 where another writer touches p1 after the resolver loaded it."""
    ledger = tmp_path / "predictions.json"
    ledger.write_text(json.dumps({"predictions": [_row("p1"), _row("p2")], "resolved": [],
                                  "stats": {"correct": 0, "wrong": 0, "pending": 2}}))
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(ledger))
    real_watchdog = resolver.check_resolver_watchdog
    fired = []

    def concurrent_writer(*a, **k):
        if not fired:
            fired.append(True)
            disk = json.loads(ledger.read_text())
            disk["predictions"][0]["note"] = "touched by another writer"
            ledger.write_text(json.dumps(disk))
        return real_watchdog(*a, **k)

    monkeypatch.setattr(resolver, "check_resolver_watchdog", concurrent_writer)
    return ledger


def _assert_matches_disk(out, ledger):
    disk = json.loads(ledger.read_text())
    assert [r["id"] for r in disk["predictions"]] == ["p1"]
    assert [r["id"] for r in disk["resolved"]] == ["p2"]
    assert [r["id"] for r in out["pending"]] == ["p1"]
    assert [r["id"] for r in out["resolved"]] == ["p2"]
    assert out["stats"]["pending"] == 1
    assert out["watchdog"]["pending_count"] == 1


def test_expire_conflict_returns_committed_snapshot(conflicted_ledger):
    out = resolver.expire_stale_predictions()
    _assert_matches_disk(out, conflicted_ledger)


def test_resolve_due_conflict_returns_committed_snapshot(conflicted_ledger, monkeypatch):
    monkeypatch.setattr(resolver, "fetch_prices", lambda subnets=None: {})
    out = resolver.resolve_due_predictions([])
    _assert_matches_disk(out, conflicted_ledger)


def test_regrade_conflict_stats_ignore_a_later_disk_fault(tmp_path, monkeypatch):
    ledger = tmp_path / "predictions.json"
    expired = dict(_row("p1"), status="expired", outcome="expired",
                   retirement_reason="missing_price_at_horizon", resolve_at="2000-01-01T00:00:00Z")
    ledger.write_text(json.dumps({"predictions": [], "resolved": [expired, dict(expired, id="p3"), _row("p2")],
                                  "stats": {"correct": 0, "wrong": 0, "pending": 0}}))
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(ledger))
    real_commit = resolver._commit_ledger_changes
    snapshots = []

    def commit_then_corrupt(*a, **k):
        disk = json.loads(ledger.read_text())
        disk["resolved"][0]["note"] = "touched by another writer"
        ledger.write_text(json.dumps(disk))
        result = real_commit(*a, **k)
        assert result.conflicts, "setup must produce a conflicted commit"
        snapshots.append(json.loads(ledger.read_text())["stats"])
        ledger.write_text(json.dumps({"stats": None}))
        return result

    monkeypatch.setattr(resolver, "_commit_ledger_changes", commit_then_corrupt)
    out = resolver.regrade_expired_predictions(live_prices={})
    assert snapshots, "regrade did not commit"
    assert out["stats"] == snapshots[0]
