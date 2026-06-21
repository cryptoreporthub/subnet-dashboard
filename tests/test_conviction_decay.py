"""
Tests for conviction decay math.
"""

import math
import time
from datetime import datetime, timezone

import pytest

from internal.conviction_decay import (
    DECAY_PRUNE_THRESHOLD,
    DECAY_RESISTANCE_MULTIPLIER,
    DEFAULT_HALF_LIFE_HOURS,
    apply_decay_to_nodes,
    compute_alpha,
    get_half_life,
    is_pruned,
    node_metadata,
)


def _iso(hours_ago: float) -> str:
    """Return an ISO timestamp hours_ago from now."""
    from datetime import timedelta
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.isoformat()


class TestComputeAlpha:
    def test_fresh_node_alpha_is_one(self):
        """A node created just now should have alpha ~1.0."""
        alpha = compute_alpha(_iso(0), half_life_hours=1.0)
        assert alpha >= 0.999  # floating point: tiny delay between timestamp and compute

    def test_exactly_one_half_life(self):
        """After exactly one half-life, alpha should be 0.5."""
        hl = 2.0
        alpha = compute_alpha(_iso(hl), half_life_hours=hl)
        assert abs(alpha - 0.5) < 0.001

    def test_two_half_lives(self):
        """After two half-lives, alpha should be 0.25."""
        hl = 1.0
        alpha = compute_alpha(_iso(2 * hl), half_life_hours=hl)
        assert abs(alpha - 0.25) < 0.001

    def test_signal_type_defaults(self):
        """Signal type should map to correct half-life."""
        alpha = compute_alpha(_iso(0.33), signal_type="whale_alert")
        assert abs(alpha - 0.5) < 0.01  # ~0.33h half-life, 0.33h elapsed

    def test_unknown_signal_type_uses_default(self):
        """Unknown signal types should use the default half-life."""
        hl = DEFAULT_HALF_LIFE_HOURS["default"]
        alpha = compute_alpha(_iso(hl), signal_type="nonexistent")
        assert abs(alpha - 0.5) < 0.001

    def test_decay_resistance_for_correct_prediction(self):
        """Correct predictions (score >= 0.7) get 3x half-life."""
        hl = 2.0
        # After 2 hours (1 normal half-life), alpha should be higher due to resistance.
        alpha_normal = compute_alpha(_iso(hl), half_life_hours=hl)
        alpha_resistant = compute_alpha(_iso(hl), half_life_hours=hl, outcome_score=0.8)
        assert alpha_resistant > alpha_normal
        # With 3x resistance, effective half-life is 6h, so after 2h:
        # alpha = e^(-ln(2)*2/6) = e^(-0.231) ≈ 0.794
        assert abs(alpha_resistant - 0.794) < 0.01

    def test_no_decay_resistance_for_wrong_prediction(self):
        """Wrong predictions (score < 0.3) decay normally."""
        hl = 2.0
        alpha_normal = compute_alpha(_iso(hl), half_life_hours=hl)
        alpha_wrong = compute_alpha(_iso(hl), half_life_hours=hl, outcome_score=0.1)
        assert abs(alpha_normal - alpha_wrong) < 0.001

    def test_alpha_never_negative(self):
        """Alpha should never go below 0."""
        alpha = compute_alpha(_iso(1000), half_life_hours=0.1)
        assert alpha == 0.0


class TestIsPruned:
    def test_below_threshold_is_pruned(self):
        assert is_pruned(0.01, threshold=0.05) is True

    def test_above_threshold_not_pruned(self):
        assert is_pruned(0.5, threshold=0.05) is False

    def test_exactly_at_threshold_not_pruned(self):
        assert is_pruned(0.05, threshold=0.05) is False

    def test_default_threshold(self):
        assert is_pruned(0.01) is True
        assert is_pruned(0.5) is False


class TestApplyDecayToNodes:
    def test_splits_active_and_pruned(self):
        nodes = [
            {**node_metadata("whale_alert"), "id": "fresh"},
            {"id": "old", "created_at": _iso(100), "half_life_hours": 0.1, "signal_type": "default"},
        ]
        result = apply_decay_to_nodes(nodes)
        assert result["active_count"] == 1
        assert result["pruned_count"] == 1
        assert result["active"][0]["id"] == "fresh"
        assert result["pruned"][0]["id"] == "old"

    def test_all_nodes_have_alpha(self):
        nodes = [
            {**node_metadata("emission_change"), "id": "a"},
            {**node_metadata("governance"), "id": "b"},
        ]
        result = apply_decay_to_nodes(nodes)
        for node in result["active"]:
            assert "alpha" in node
            assert "decayed_at" in node
            assert "pruned" in node

    def test_empty_nodes(self):
        result = apply_decay_to_nodes([])
        assert result["active_count"] == 0
        assert result["pruned_count"] == 0


class TestGetHalfLife:
    def test_known_types(self):
        assert get_half_life("whale_alert") == 0.33
        assert get_half_life("emission_change") == 1.4
        assert get_half_life("discord_spike") == 2.3
        assert get_half_life("governance") == 14.0

    def test_unknown_type_returns_default(self):
        assert get_half_life("nonexistent") == DEFAULT_HALF_LIFE_HOURS["default"]


class TestNodeMetadata:
    def test_includes_all_fields(self):
        meta = node_metadata("whale_alert", outcome_score=0.8)
        assert meta["signal_type"] == "whale_alert"
        assert meta["half_life_hours"] == 0.33
        assert meta["outcome_score"] == 0.8
        assert meta["alpha"] == 1.0
        assert meta["pruned"] is False
        assert "created_at" in meta

    def test_custom_half_life(self):
        meta = node_metadata("custom", half_life_hours=5.0)
        assert meta["half_life_hours"] == 5.0