from __future__ import annotations

import json
from datetime import datetime, timezone


def test_recovery_uses_canonical_finalize_and_resolves_status(tmp_path, monkeypatch):
    from internal.council import resolver
    from internal.council import price_reference
    from internal.learning import expired_recovery, predictions_store

    predictions_path = tmp_path / "predictions.json"
    resolve_at = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    predictions_path.write_text(
        json.dumps(
            {
                "predictions": [],
                "resolved": [
                    {
                        "id": "expired-1",
                        "netuid": 7,
                        "status": "expired",
                        "outcome": "expired",
                        "correct": None,
                        "direction": "up",
                        "reference_price": 100.0,
                        "predicted_pct": 5.0,
                        "resolve_at": resolve_at.isoformat().replace("+00:00", "Z"),
                    }
                ],
            }
        )
    )
    monkeypatch.setattr(predictions_store, "PREDICTIONS_PATH", str(predictions_path))
    monkeypatch.setattr(
        price_reference,
        "price_at_resolve_at",
        lambda *args, **kwargs: ("ok", 110.0, {"price_source": "hourly"}),
    )
    monkeypatch.setattr(resolver, "_stamp_and_nudge_expert", lambda *args, **kwargs: ("quant", False))
    monkeypatch.setattr(resolver, "_ensure_subnet_snapshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(resolver, "_skip_council_learning", lambda *args, **kwargs: True)
    monkeypatch.setattr(resolver, "atomic_finalize_resolution", resolver.atomic_finalize_resolution)

    result = expired_recovery.recover_expired_predictions()
    saved = json.loads(predictions_path.read_text())
    row = saved["resolved"][0]

    assert result["recovered"] == 1
    assert row["status"] == "resolved"
    assert row["outcome"] == "hit"
    assert row["correct"] is True
    assert row["resolved_price"] == 110.0
