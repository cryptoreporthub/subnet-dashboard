"""Regression: replay must not credit stale expert=quant stamps to quant.

Old ledger rows were stamped expert=quant by the raw _normalize_expert path
before the Grok LOCK fix. expert_for_replay_row must re-derive attribution
from signal_impact / signal_source / pick-blob and ignore the baked-in field,
so dark_horse rows get the correct weight uplift during replay.
"""

from __future__ import annotations

import json

import pytest

from internal.council.signal_expert import expert_for_replay_row
from internal.council.weights import DEFAULT_WEIGHTS, replay_weights_from_predictions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolved_row(*, signal_source=None, signal_impact=None, expert="quant", correct=True, ts="2026-01-01T00:00:00Z"):
    row = {"resolved_at": ts, "correct": correct, "expert": expert}
    if signal_source is not None:
        row["signal_source"] = signal_source
    if signal_impact is not None:
        row["signal_impact"] = signal_impact
    return row


def _preds_file(tmp_path, rows):
    p = tmp_path / "predictions.json"
    p.write_text(json.dumps({"predictions": [], "resolved": rows}))
    return str(p)


# ---------------------------------------------------------------------------
# Unit: expert_for_replay_row ignores stale expert field
# ---------------------------------------------------------------------------

def test_expert_for_replay_row_ignores_stale_expert_stamp_via_signal_source():
    """signal_source=delegation_flow → dark_horse, even when expert=quant."""
    row = _resolved_row(signal_source="delegation_flow", expert="quant")
    assert expert_for_replay_row(row) == "dark_horse"


def test_expert_for_replay_row_ignores_stale_expert_stamp_via_signal_impact():
    """signal_impact with delegation_flow lead → dark_horse, ignoring expert=quant."""
    row = _resolved_row(
        expert="quant",
        signal_impact={
            "impacts": [
                {"signal_type": "delegation_flow", "magnitude_pct": 15.0, "learned_weight": 1.2},
                {"signal_type": "emission_momentum", "magnitude_pct": 5.0, "learned_weight": 1.0},
            ]
        },
    )
    assert expert_for_replay_row(row) == "dark_horse"


def test_expert_for_replay_row_signal_impact_overrides_stale_quant():
    """signal_impact must override expert=quant even when signal_source is absent."""
    row = {
        "correct": True,
        "expert": "quant",
        "resolved_at": "2026-01-01T00:00:00Z",
        "signal_impact": {
            "impacts": [
                {"signal_type": "delegation_flow", "magnitude_pct": 10.0, "learned_weight": 1.0},
            ]
        },
    }
    assert expert_for_replay_row(row) == "dark_horse"


def test_expert_for_replay_row_onchain_flow_signal_source():
    """onchain_flow maps to dark_horse regardless of baked-in expert."""
    row = _resolved_row(signal_source="onchain_flow", expert="quant")
    assert expert_for_replay_row(row) == "dark_horse"


def test_expert_for_replay_row_technical_via_signal_impact_not_overridden_by_stale_dark_horse():
    """Ensure correct attribution for technical rows even when stale stamp says dark_horse."""
    row = _resolved_row(
        expert="dark_horse",
        signal_impact={
            "impacts": [
                {"signal_type": "rsi_crossover", "magnitude_pct": 20.0, "learned_weight": 1.0},
            ]
        },
    )
    assert expert_for_replay_row(row) == "technical"


# ---------------------------------------------------------------------------
# Integration: replay_weights_from_predictions credits dark_horse correctly
# ---------------------------------------------------------------------------

def test_replay_dark_horse_uplift_from_stale_quant_rows(tmp_path):
    """Rows stamped expert=quant but attributed to dark_horse via signal_source
    must produce dark_horse weight uplift, not quant uplift."""
    rows = [
        _resolved_row(signal_source="delegation_flow", expert="quant", correct=True, ts="2026-01-01T00:00:00Z"),
        _resolved_row(signal_source="delegation_flow", expert="quant", correct=True, ts="2026-01-02T00:00:00Z"),
        _resolved_row(signal_source="delegation_flow", expert="quant", correct=True, ts="2026-01-03T00:00:00Z"),
    ]
    path = _preds_file(tmp_path, rows)
    weights = replay_weights_from_predictions(path, include_archive=False)

    # dark_horse should be lifted by three correct nudges
    expected_dh = round(
        min(DEFAULT_WEIGHTS["dark_horse"] + 3 * 0.02, 2.0),
        4,
    )
    assert weights["dark_horse"] == expected_dh, (
        f"dark_horse expected {expected_dh}, got {weights['dark_horse']}"
    )
    # quant must be untouched (these rows belong to dark_horse, not quant)
    assert weights["quant"] == DEFAULT_WEIGHTS["quant"], (
        f"quant must not be nudged; got {weights['quant']}"
    )


def test_replay_dark_horse_uplift_via_signal_impact(tmp_path):
    """Rows stamped expert=quant but with delegation_flow in signal_impact
    must produce dark_horse weight uplift during replay."""
    rows = [
        _resolved_row(
            expert="quant",
            correct=True,
            ts=f"2026-01-0{i+1}T00:00:00Z",
            signal_impact={
                "impacts": [
                    {"signal_type": "delegation_flow", "magnitude_pct": 12.0, "learned_weight": 1.1},
                ]
            },
        )
        for i in range(4)
    ]
    path = _preds_file(tmp_path, rows)
    weights = replay_weights_from_predictions(path, include_archive=False)

    expected_dh = round(min(DEFAULT_WEIGHTS["dark_horse"] + 4 * 0.02, 2.0), 4)
    assert weights["dark_horse"] == expected_dh
    assert weights["quant"] == DEFAULT_WEIGHTS["quant"]


def test_replay_mixed_correct_incorrect_dark_horse_rows(tmp_path):
    """Mix of correct and incorrect dark_horse rows (all stamped quant) produces
    the expected net dark_horse delta."""
    rows = [
        _resolved_row(signal_source="delegation_flow", expert="quant", correct=True,  ts="2026-01-01T00:00:00Z"),
        _resolved_row(signal_source="delegation_flow", expert="quant", correct=False, ts="2026-01-02T00:00:00Z"),
        _resolved_row(signal_source="delegation_flow", expert="quant", correct=True,  ts="2026-01-03T00:00:00Z"),
    ]
    path = _preds_file(tmp_path, rows)
    weights = replay_weights_from_predictions(path, include_archive=False)

    # net: +0.02 -0.03 +0.02 = +0.01
    expected_dh = round(DEFAULT_WEIGHTS["dark_horse"] + 0.01, 4)
    assert weights["dark_horse"] == pytest.approx(expected_dh, abs=1e-4)
    assert weights["quant"] == DEFAULT_WEIGHTS["quant"]
