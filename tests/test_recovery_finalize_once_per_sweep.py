"""A row recovered in a sweep gets one finalize attempt in that sweep.

An unrelated row with a pending effect turns on the retry pass. That pass must
not finalize the newly recovered row a second time.
"""

from __future__ import annotations

import json

import pytest

from internal.judges import portfolios


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    from internal.council import price_reference, resolver
    from internal.learning import expired_recovery, predictions_store

    port_path = tmp_path / "judge_portfolios.json"
    port_path.write_text(json.dumps({"portfolios": {}}))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    receipts = tmp_path / "learning_effect_receipts.json"
    monkeypatch.setattr(expired_recovery, "LEARNING_EFFECT_RECEIPTS_PATH", str(receipts), raising=False)
    monkeypatch.setenv("LEARNING_EFFECT_RECEIPTS_PATH", str(receipts))

    old_done = {
        "id": "old-done", "netuid": 7, "status": "resolved", "outcome": "hit", "correct": True,
        "direction": "up", "reference_price": 100.0, "resolved_price": 110.0, "actual_pct": 10.0,
        "predicted_pct": 5.0, "resolve_at": "2026-07-01T12:00:00Z",
        "learning_effects": {"pending": ["signal"], "indeterminate": []},
    }
    exp_new = {
        "id": "exp-new", "netuid": 8, "status": "expired", "outcome": "expired", "direction": "up",
        "reference_price": 100.0, "predicted_pct": 5.0, "resolve_at": "2026-07-01T12:00:00Z",
    }
    path = tmp_path / "predictions.json"
    path.write_text(json.dumps({"predictions": [], "resolved": [old_done, exp_new]}))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(path))
    monkeypatch.setattr(
        price_reference,
        "price_at_resolve_at",
        lambda *args, **kwargs: ("ok", 110.0, {"price_source": "hourly"}),
    )
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *args, **kwargs: True)
    return path


def test_failed_finalize_runs_once_per_sweep(ledger, monkeypatch):
    from internal.council import resolver
    from internal.learning import expired_recovery

    finalized = []

    def close_fails(row, **kwargs):
        finalized.append(row.get("id"))
        row.setdefault("side_effect_warnings", []).append("on_prediction_resolved")

    monkeypatch.setattr(resolver, "atomic_finalize_resolution", close_fails)

    first = expired_recovery.recover_expired_predictions()

    assert finalized == ["exp-new"]
    assert first["incomplete_ids"] == ["exp-new"]
    rows = {r["id"]: r for r in json.loads(ledger.read_text())["resolved"]}
    assert rows["old-done"]["learning_effects"]["done"] == ["signal"]
    assert rows["exp-new"]["learning_effects"]["pending"] == ["finalize"]

    finalized.clear()
    second = expired_recovery.recover_expired_predictions()

    assert finalized == ["exp-new"]
    assert second["incomplete_ids"] == ["exp-new"]
