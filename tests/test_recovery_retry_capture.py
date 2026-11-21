"""A recovery retry must hand the stored capture to the learning effects, not None."""

from __future__ import annotations

import json

import pytest

from internal.judges import portfolios


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    port_path = tmp_path / "judge_portfolios.json"
    port_path.write_text("{}")
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    from internal.learning import expired_recovery
    receipts = tmp_path / "learning_effect_receipts.json"
    monkeypatch.setattr(expired_recovery, "LEARNING_EFFECT_RECEIPTS_PATH", str(receipts), raising=False)
    monkeypatch.setenv("LEARNING_EFFECT_RECEIPTS_PATH", str(receipts))


def test_retry_passes_stored_capture_to_effects(tmp_path, monkeypatch):
    from internal.council import capture as capture_mod
    from internal.learning import expired_recovery, predictions_store

    row = {
        "id": "resolved-pending-1",
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

    expected = capture_mod.capture_from_row(row)
    assert expected is not None, "fixture must carry a stored capture"

    from internal.council import price_reference, resolver

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

    expired_recovery.recover_expired_predictions()

    assert seen, "retry did not reach the signal-weight nudge"
    assert seen[0] == expected
