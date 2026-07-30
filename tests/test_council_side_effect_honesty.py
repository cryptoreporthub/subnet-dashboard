"""Council side-effect honesty — silent failures must surface warnings."""

from __future__ import annotations

from unittest.mock import patch

from internal.council.resolver import atomic_finalize_resolution
from internal.council.weights import rebalance_council_weights


def test_atomic_finalize_records_side_effect_warnings(tmp_path, monkeypatch):
    pred = {
        "id": "p1",
        "expert": "quant",
        "status": "open",
    }

    def _boom(*_a, **_k):
        raise RuntimeError("trace down")

    with patch("internal.council.resolver.on_prediction_resolved", side_effect=_boom):
        with patch(
            "internal.council.prediction_trace.record_prediction_resolved",
            side_effect=_boom,
        ):
            with patch(
                "internal.learning.trail_events.emit_prediction_resolved",
                side_effect=_boom,
            ):
                with patch(
                    "internal.council.pick_history.finalize_from_prediction",
                    side_effect=_boom,
                ):
                    out = atomic_finalize_resolution(
                        pred,
                        actual_pct=1.0,
                        outcome="hit",
                        correct=True,
                        resolved_price=1.0,
                        resolved_at="2026-07-30T00:00:00Z",
                    )
    assert out["status"] == "resolved"
    assert "on_prediction_resolved" in out.get("side_effect_warnings", [])
    assert "emit_prediction_resolved" in out["side_effect_warnings"]


def test_rebalance_trail_emitted_false_on_emit_failure(tmp_path, monkeypatch):
    soul = tmp_path / "soul_map.json"
    preds = tmp_path / "predictions.json"
    soul.write_text(
        '{"adversarial_state":{"council_weights":{"quant":1,"hype":1,"dark_horse":1,"technical":1}}}',
        encoding="utf-8",
    )
    preds.write_text('{"resolved":[],"active":[]}', encoding="utf-8")

    def _boom(*_a, **_k):
        raise RuntimeError("trail bus down")

    with patch("internal.learning.trail_bus.emit_weight_change", side_effect=_boom):
        # Force a weight delta so emit path is taken: soft_blend may still change vs prior.
        result = rebalance_council_weights(
            predictions_path=str(preds),
            soul_map_path=str(soul),
            save=True,
        )
    assert result["ok"] is True
    assert result["saved"] is True
    # emit may no-op if no weight deltas; force via patching the loop by changing before
    # If no deltas, trail_emitted stays True (emit never called). Re-run with mocked before/after.
    with patch("internal.council.weights.save_weights"):
        with patch("internal.council.weights.load_weights", return_value={"quant": 2.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}):
            with patch(
                "internal.council.weights.soft_blend_weights",
                return_value={"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0},
            ):
                with patch("internal.council.weights.replay_weights_from_predictions", return_value={"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}):
                    with patch("internal.council.weights.merged_replay_rows", return_value=([], {})):
                        with patch("internal.learning.trail_bus.emit_weight_change", side_effect=_boom):
                            result2 = rebalance_council_weights(
                                predictions_path=str(preds),
                                soul_map_path=str(soul),
                                save=True,
                            )
    assert result2["trail_emitted"] is False
    assert "emit_weight_change" in result2.get("warnings", [])
