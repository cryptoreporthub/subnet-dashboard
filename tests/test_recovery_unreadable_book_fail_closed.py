"""An unreadable judge book must stop recovery before any learning effect runs."""

from __future__ import annotations

import json

import pytest

from internal.judges import portfolios


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    port_path = tmp_path / "judge_portfolios.json"
    port_path.write_text("{not json")
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    from internal.learning import expired_recovery
    receipts = tmp_path / "learning_effect_receipts.json"
    monkeypatch.setattr(expired_recovery, "LEARNING_EFFECT_RECEIPTS_PATH", str(receipts), raising=False)
    monkeypatch.setenv("LEARNING_EFFECT_RECEIPTS_PATH", str(receipts))


def test_pending_effect_does_not_run_on_unreadable_book(tmp_path, monkeypatch):
    from internal.council import price_reference, resolver
    from internal.learning import expired_recovery, predictions_store

    row = {
        "id": "resolved-pending-2",
        "netuid": 7,
        "status": "resolved",
        "outcome": "hit",
        "correct": True,
        "direction": "up",
        "reference_price": 100.0,
        "resolved_price": 110.0,
        "actual_pct": 10.0,
        "predicted_pct": 5.0,
        "resolve_at": "2026-07-01T12:00:00Z",
        "learning_effects": {"pending": ["signal"], "indeterminate": []},
    }
    ledger = tmp_path / "predictions.json"
    ledger.write_text(json.dumps({"predictions": [], "resolved": [row]}))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(ledger))

    seen = []
    monkeypatch.setattr(
        price_reference,
        "price_at_resolve_at",
        lambda *args, **kwargs: ("ok", 110.0, {"price_source": "hourly"}),
    )
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        resolver,
        "_nudge_signal_weights",
        lambda _row, _correct, capture=None: seen.append(capture),
    )

    out = expired_recovery.recover_expired_predictions()

    assert out.get("ok") is False, "recovery must fail closed on an unreadable book"
    assert seen == [], "a learning effect ran against an unreadable judge book"
