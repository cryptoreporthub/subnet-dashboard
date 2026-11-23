"""Stale contrarian weight merge + replay repair."""

import json

from internal.council.weights import (
    load_weights,
    normalize_council_weights,
    replay_weights_from_predictions,
)


def _stored_experts(soul):
    from internal.store import ledger_db

    with ledger_db.reader(str(soul)) as conn:
        return ledger_db.read_kind(conn, "expert")


def test_replay_weights_counts_legacy_contrarian_as_dark_horse(tmp_path):
    soul = tmp_path / "soul_map.json"
    preds = tmp_path / "predictions.json"
    soul.write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "council_weights": {
                        "quant": 0.41,
                        "hype": 0.1,
                        "contrarian": 1.08,
                        "dark_horse": 0.14,
                        "technical": 0.12,
                    }
                }
            }
        )
    )
    preds.write_text(
        json.dumps(
            {
                "predictions": [],
                "resolved": [
                    {"expert": "contrarian", "correct": False, "resolved_at": "2026-01-01T00:00:00Z"},
                    {"expert": "contrarian", "correct": False, "resolved_at": "2026-01-02T00:00:00Z"},
                    {"expert": "dark_horse", "correct": True, "resolved_at": "2026-01-03T00:00:00Z"},
                ],
            }
        )
    )

    replayed = replay_weights_from_predictions(str(preds))
    assert replayed["dark_horse"] == 0.96  # 1.0 -0.03 -0.03 +0.02

    load_weights(str(soul))
    stored = _stored_experts(soul)
    assert "contrarian" not in stored
    assert stored["dark_horse"] == 0.96


def test_load_weights_repairs_stale_contrarian(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    preds = tmp_path / "predictions.json"
    soul.write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "council_weights": {
                        "quant": 1.0,
                        "hype": 1.0,
                        "contrarian": 1.08,
                        "dark_horse": 0.1,
                        "technical": 1.0,
                    }
                }
            }
        )
    )
    preds.write_text(json.dumps({"predictions": [], "resolved": []}))
    monkeypatch.setattr("internal.council.weights.SOUL_MAP_PATH", str(soul))

    load_weights(str(soul))
    stored = _stored_experts(soul)
    assert stored["dark_horse"] == 1.0
    assert "contrarian" not in stored


def test_normalize_no_longer_pins_stale_contrarian():
    out = normalize_council_weights(
        {"quant": 0.41, "hype": 0.1, "contrarian": 1.08, "dark_horse": 0.14, "technical": 0.12}
    )
    assert out["dark_horse"] == 0.14
