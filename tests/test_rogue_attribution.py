"""Rogue attribution fix - unit tests.

Covers the fallback-to-rogue change, the replay guard (archive hygiene), the
rogue bucket never touching scored weights, the RELATIVE promotion rule, and
the rebalance math (quant 2.00 -> 1.50).
"""

from __future__ import annotations

import pytest

from internal.council.expert_display import (
    CANONICAL_EXPERTS,
    ROGUE_EXPERT,
    leading_expert_for_pick,
)
from internal.council.expert_attribution import resolve_expert_attribution
from internal.council.signal_expert import expert_for_replay_row
from internal.learning.weight_deltas import _ROGUE_PROMOTION_RULE, build_rogue_stats


def test_rogue_is_not_a_scored_expert() -> None:
    assert ROGUE_EXPERT == "rogue"
    assert ROGUE_EXPERT not in CANONICAL_EXPERTS


def test_unresolved_pick_falls_back_to_rogue_not_quant() -> None:
    pick = {"expert_contributions": None, "active_signals": []}
    leader, label, _score = leading_expert_for_pick(pick)
    assert leader == "rogue"
    assert label == "Rogue"


def test_resolve_expert_attribution_returns_rogue_on_failure() -> None:
    expert, source = resolve_expert_attribution({"price": 1.0})
    assert expert == "rogue"
    assert source == "unresolved"


def test_replay_guard_routes_bare_stamp_to_rogue() -> None:
    # Legacy fallback stamped expert="quant" with zero attributable evidence.
    row = {"expert": "quant", "correct": True, "netuid": 1}
    assert expert_for_replay_row(row) == "rogue"


def test_replay_keeps_real_signal_evidence() -> None:
    row = {"signal_source": "rsi_crossover", "expert": "technical", "correct": True}
    assert expert_for_replay_row(row) == "technical"


def test_rogue_promotion_rule_is_relative_to_incumbents() -> None:
    # An absolute 55% bar can sit above every real expert's observed hit rate;
    # the rule must be relative to the leading expert instead.
    assert "leading" in _ROGUE_PROMOTION_RULE
    assert "0.55" not in _ROGUE_PROMOTION_RULE


def test_rogue_stats_default_shape() -> None:
    stats = build_rogue_stats()
    assert stats["tracked"] is True
    assert "count" in stats
    assert "hit_rate" in stats
    assert "promotion_rule" in stats
    assert "council_best_hit_rate" in stats or "council_avg_hit_rate" in stats


@pytest.mark.parametrize("weight,expected", [(2.0, 1.5), (1.0, 1.0), (0.4, 0.7), (3.0, 2.0)])
def test_rebalance_mean_revert(weight: float, expected: float) -> None:
    from scripts.rebalance_expert_weights import mean_revert

    out = mean_revert({"quant": weight})
    assert abs(out["quant"] - expected) < 1e-9
