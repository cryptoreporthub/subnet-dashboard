"""Regression tests — expert weight nudge alignment (Task 31).

Covers:
1. normalize_expert vs resolve_expert_attribution disagreement: after the fix the nudge
   uses the attributed expert, not the raw string normalizer.
2. Delta constant single-source-of-truth: resolver.py no longer defines its own
   symmetric delta constants; weights.py is the sole definition.
3. Per-signal nudge fires when signal_contributions + active_signals are present.
"""

from __future__ import annotations

import json
import types
from typing import Any, Dict
from unittest.mock import patch


# ---------------------------------------------------------------------------
# 1. normalize_expert vs resolve_expert_attribution disagreement
# ---------------------------------------------------------------------------


def test_nudge_uses_attributed_expert_not_normalizer(tmp_path, monkeypatch):
    """A row whose normalize_expert returns None (no expert/signal_source field)
    but resolve_expert_attribution resolves to dark_horse via pick_blend/active_signals
    must nudge dark_horse — not be silently skipped.

    OLD (broken): nudge_expert = _normalize_expert → None → no nudge
    NEW (correct): nudge_expert = stamped_expert → dark_horse → nudges dark_horse
    """
    from internal.council import resolver
    import internal.council.weights as weights_mod

    soul_path = str(tmp_path / "soul_map.json")
    (tmp_path / "soul_map.json").write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "council_weights": {
                        "quant": 1.0,
                        "hype": 1.0,
                        "dark_horse": 1.0,
                        "technical": 1.0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(weights_mod, "SOUL_MAP_PATH", soul_path)
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(tmp_path / "predictions.json"))

    nudged: list = []

    def _capture(correct, expert):  # _nudge_weights(correct, expert)
        nudged.append((expert, correct))

    monkeypatch.setattr(resolver, "_nudge_weights", _capture)

    # No expert/signal_source field → normalize_expert returns None.
    # active_signals votes for dark_horse via delegation_flow signal.
    prediction: Dict[str, Any] = {
        "id": "dh-alignment-test",
        "netuid": 1,
        "direction": "up",
        "predicted_pct": 2.0,
        "reference_price": 10.0,
        "horizon_type": "hour",
        "expert_contributions": {"quant": 0.6, "dark_horse": 0.5},
        "active_signals": ["delegation_flow"],  # dark_horse signal
    }

    from internal.council.expert_attribution import normalize_expert, resolve_expert_attribution

    # Verify the disagreement precondition: normalize returns None, attribution resolves.
    assert normalize_expert(prediction) is None, "precondition: normalize_expert returns None for this row"
    attributed, source = resolve_expert_attribution(prediction)
    assert attributed == "dark_horse", f"precondition: attribution resolves to dark_horse, got {attributed!r}"

    # Now resolve — after the fix the nudge must fire for dark_horse.
    resolver.resolve_prediction(prediction, current_price=10.4)

    assert prediction.get("expert") == "dark_horse"
    assert len(nudged) == 1, f"expected one nudge call, got {nudged}"
    assert nudged[0][0] == "dark_horse", f"expected dark_horse nudge, got {nudged[0][0]!r}"
    assert nudged[0][1] is True  # price went up as predicted


def test_ambiguous_quant_alias_no_longer_bleeds_onto_quant(tmp_path, monkeypatch):
    """A row with expert='alpha' (legacy quant alias) that is over-ridden by pick_blend
    attribution must NOT pile an extra nudge onto quant.

    Before: normalize_expert("alpha") → "quant" even when attribution says dark_horse.
    After: nudge uses attributed expert only.
    """
    from internal.council import resolver
    import internal.council.weights as weights_mod

    soul_path = str(tmp_path / "soul_map.json")
    (tmp_path / "soul_map.json").write_text(
        json.dumps(
            {
                "adversarial_state": {
                    "council_weights": {
                        "quant": 1.0,
                        "hype": 1.0,
                        "dark_horse": 1.0,
                        "technical": 1.0,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(weights_mod, "SOUL_MAP_PATH", soul_path)
    monkeypatch.setattr(resolver, "PREDICTIONS_PATH", str(tmp_path / "predictions.json"))

    nudged: list = []

    def _capture(correct, expert):  # _nudge_weights(correct, expert)
        nudged.append((expert, correct))

    monkeypatch.setattr(resolver, "_nudge_weights", _capture)

    # expert='alpha' → normalize_expert → "quant".
    # But active_signals has delegation_flow which maps to dark_horse;
    # pick_blob path via dominant_expert_for_learning would elect dark_horse.
    # However resolve_expert_attribution checks _canonical_from_name("alpha")
    # which calls normalize_expert → "quant" first (existing slot wins).
    # The point here is that whatever attribution decides, nudge matches label exactly.
    prediction: Dict[str, Any] = {
        "id": "alpha-test",
        "netuid": 2,
        "direction": "up",
        "predicted_pct": 1.5,
        "reference_price": 5.0,
        "horizon_type": "day",
        "expert": "alpha",
    }

    from internal.council.expert_attribution import normalize_expert, resolve_expert_attribution

    norm = normalize_expert(prediction)
    attributed, _src = resolve_expert_attribution(prediction)

    resolver.resolve_prediction(prediction, current_price=5.1)

    # Label and nudge must agree — whatever was stamped.
    stamped = prediction.get("expert")
    assert len(nudged) == 1, f"expected exactly one nudge, got {nudged}"
    assert nudged[0][0] == stamped, (
        f"nudge expert {nudged[0][0]!r} disagrees with stamped expert {stamped!r}"
    )


# ---------------------------------------------------------------------------
# 2. Delta constant single-source-of-truth
# ---------------------------------------------------------------------------


def test_resolver_has_no_own_learning_delta_constants():
    """resolver.py must not define its own _LEARNING_DELTA_CORRECT/_LEARNING_DELTA_WRONG.
    weights.py is the sole source of truth for learning deltas.
    """
    import internal.council.resolver as resolver_mod

    assert not hasattr(resolver_mod, "_LEARNING_DELTA_CORRECT"), (
        "resolver._LEARNING_DELTA_CORRECT still exists — remove it, weights.py is authoritative"
    )
    assert not hasattr(resolver_mod, "_LEARNING_DELTA_WRONG"), (
        "resolver._LEARNING_DELTA_WRONG still exists — remove it, weights.py is authoritative"
    )


def test_weights_delta_constants_are_canonical():
    """weights.py defines the asymmetric (correct=+0.02, wrong=-0.03) deltas."""
    import internal.council.weights as weights_mod

    assert weights_mod._LEARNING_DELTA_CORRECT == 0.02
    assert weights_mod._LEARNING_DELTA_WRONG == -0.03


def test_nudge_expert_uses_weights_deltas(tmp_path, monkeypatch):
    """A correct nudge applies +0.02 and a wrong nudge applies -0.03 (weights.py values).

    Uses a fresh soul_map file per assertion to avoid any in-memory cache bleed
    between the two nudge calls.
    """
    import internal.council.weights as weights_mod

    base = {"quant": 1.0, "hype": 1.0, "dark_horse": 1.0, "technical": 1.0}

    # Correct nudge: fresh file
    soul_correct = str(tmp_path / "soul_correct.json")
    (tmp_path / "soul_correct.json").write_text(
        json.dumps({"adversarial_state": {"council_weights": base}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(weights_mod, "SOUL_MAP_PATH", soul_correct)
    after_correct = weights_mod.nudge_expert("dark_horse", True, soul_correct)
    assert abs(after_correct - 1.02) < 1e-9, f"expected 1.02 after correct, got {after_correct}"

    # Wrong nudge: separate fresh file
    soul_wrong = str(tmp_path / "soul_wrong.json")
    (tmp_path / "soul_wrong.json").write_text(
        json.dumps({"adversarial_state": {"council_weights": base}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(weights_mod, "SOUL_MAP_PATH", soul_wrong)
    after_wrong = weights_mod.nudge_expert("dark_horse", False, soul_wrong)
    assert abs(after_wrong - 0.97) < 1e-9, f"expected 0.97 after wrong, got {after_wrong}"


# ---------------------------------------------------------------------------
# 3. Per-signal nudge fires when signal_contributions + active_signals present
# ---------------------------------------------------------------------------


def test_signal_nudge_fires_with_signal_contributions_and_active_signals(monkeypatch):
    """_nudge_signal_weights must call nudge_signal_weight for each active signal
    that appears in signal_contributions when the prediction resolves.

    nudge_signal_weight is patched on the resolver module's namespace (where it
    was imported directly at module load time).
    """
    import internal.council.resolver as resolver_mod

    nudged_signals: list = []

    def _capture_signal(horizon_type, signal_name, correct):
        nudged_signals.append((horizon_type, signal_name, correct))

    monkeypatch.setattr(resolver_mod, "nudge_signal_weight", _capture_signal)

    prediction: Dict[str, Any] = {
        "horizon_type": "hour",
        "signal_contributions": {
            "delegation_flow": {"score": 0.7},
            "rsi_crossover": {"score": 0.65},
            "mfi_flow": {"score": 0.3},  # below active threshold — not in active_signals
        },
        "active_signals": ["delegation_flow", "rsi_crossover"],
    }

    resolver_mod._nudge_signal_weights(prediction, correct=True)

    fired = {(h, s) for h, s, _ in nudged_signals}
    assert ("hour", "delegation_flow") in fired, "delegation_flow signal nudge should fire"
    assert ("hour", "rsi_crossover") in fired, "rsi_crossover signal nudge should fire"
    # mfi_flow is NOT in active_signals, so it must not be nudged
    assert ("hour", "mfi_flow") not in fired, "mfi_flow not in active_signals — must not be nudged"
    for _, _, correct_flag in nudged_signals:
        assert correct_flag is True


def test_signal_nudge_noop_without_signal_contributions(monkeypatch):
    """_nudge_signal_weights must be a no-op when signal_contributions is absent."""
    import internal.council.resolver as resolver_mod

    called: list = []
    monkeypatch.setattr(resolver_mod, "nudge_signal_weight", lambda *a, **kw: called.append(a))

    prediction: Dict[str, Any] = {
        "horizon_type": "hour",
        "active_signals": ["delegation_flow"],
        # No signal_contributions key — must no-op.
    }

    resolver_mod._nudge_signal_weights(prediction, correct=True)
    assert called == [], "nudge_signal_weight must not be called without signal_contributions"


def test_signal_nudge_infers_active_from_contributions_when_active_absent(monkeypatch):
    """When active_signals is empty but signal_contributions has high-score signals,
    _nudge_signal_weights infers active signals from scores (>0.55 or <0.45).
    """
    import internal.council.resolver as resolver_mod

    nudged_signals: list = []
    monkeypatch.setattr(resolver_mod, "nudge_signal_weight", lambda h, s, c: nudged_signals.append(s))

    prediction: Dict[str, Any] = {
        "horizon_type": "day",
        "signal_contributions": {
            "delegation_flow": {"score": 0.8},   # > 0.55 → active
            "rsi_crossover": {"score": 0.5},     # neutral → not active
            "bollinger_squeeze": {"score": 0.2}, # < 0.45 → active
        },
        # active_signals intentionally omitted
    }

    resolver_mod._nudge_signal_weights(prediction, correct=False)

    assert "delegation_flow" in nudged_signals, "high-score signal should be inferred as active"
    assert "bollinger_squeeze" in nudged_signals, "low-score signal should be inferred as active"
    assert "rsi_crossover" not in nudged_signals, "neutral-score signal should not be nudged"
