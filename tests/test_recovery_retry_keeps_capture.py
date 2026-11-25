"""A recovery retry under capture mode nudges signal weights with the stored capture.

The stored band is the grade of record. A row whose band is HIT must credit
the signal even when the raw ``correct`` flag says False.
"""

from __future__ import annotations

import json

import pytest

from internal.judges import portfolios


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    port_path = tmp_path / "judge_portfolios.json"
    port_path.write_text(json.dumps({"portfolios": {}}))
    monkeypatch.setattr(portfolios, "PORTFOLIOS_PATH", str(port_path))
    from internal.learning import expired_recovery
    receipts = tmp_path / "learning_effect_receipts.json"
    monkeypatch.setattr(expired_recovery, "LEARNING_EFFECT_RECEIPTS_PATH", str(receipts), raising=False)
    monkeypatch.setenv("LEARNING_EFFECT_RECEIPTS_PATH", str(receipts))
    monkeypatch.setenv("GRADING_MODE", "capture")


def test_retry_under_capture_mode_writes_capture_verdict(tmp_path, monkeypatch):
    from internal.council import price_reference, resolver
    from internal.learning import expired_recovery, predictions_store

    row = {
        "id": "resolved-capture-1",
        "netuid": 7,
        "status": "resolved",
        "outcome": "hit",
        "correct": False,
        "band": "hit",
        "capture_raw": 1.0,
        "capture_capped": 1.0,
        "capture_reason": "in_band",
        "direction": "up",
        "reference_price": 100.0,
        "resolved_price": 110.0,
        "actual_pct": 10.0,
        "predicted_pct": 5.0,
        "horizon_type": "hour",
        "active_signals": ["momentum"],
        "signal_contributions": {"momentum": {"score": 0.9}},
        "resolve_at": "2026-07-01T12:00:00Z",
        "learning_effects": {"pending": ["signal"], "indeterminate": []},
    }
    ledger = tmp_path / "predictions.json"
    ledger.write_text(json.dumps({"predictions": [], "resolved": [row]}))
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(ledger))

    monkeypatch.setattr(
        price_reference,
        "price_at_resolve_at",
        lambda *args, **kwargs: ("ok", 110.0, {"price_source": "hourly"}),
    )
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *args, **kwargs: False)
    monkeypatch.setattr(resolver, "_in_replay_mode", lambda: False)

    writes = []
    monkeypatch.setattr(
        resolver,
        "nudge_signal_weight",
        lambda horizon, signal, correct, **kwargs: writes.append((signal, correct, kwargs)),
    )

    expired_recovery.recover_expired_predictions()

    assert writes, "the pending signal effect never wrote a nudge"
    signal, correct, kwargs = writes[0]
    assert signal == "momentum"
    assert correct is True, "stored band HIT must credit the signal, not the raw False flag"
