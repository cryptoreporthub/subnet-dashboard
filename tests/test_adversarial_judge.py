"""
Tests for price-anchored AdversarialJudge scoring.
"""

import pytest

from internal.council.judge.adversarial import AdversarialJudge, _direction


class TestDirection:
    def test_up(self):
        assert _direction(5.0) == "up"
        assert _direction(0.01) == "up"

    def test_down(self):
        assert _direction(-5.0) == "down"
        assert _direction(-0.01) == "down"

    def test_flat(self):
        assert _direction(0.0) == "flat"
        assert _direction(0.001) == "flat"
        assert _direction(-0.001) == "flat"


class TestScorePrediction:
    def setup_method(self):
        self.judge = AdversarialJudge(persist=False)

    def test_perfect_match_scores_one(self):
        """Exact prediction match should score 1.0."""
        score = self.judge.score_prediction(5.0, 5.0, "up", "up")
        assert score == 1.0

    def test_opposite_direction_scores_zero(self):
        """Opposite direction should score 0.0."""
        score = self.judge.score_prediction(5.0, -3.0, "up", "down")
        assert score == 0.0

    def test_both_flat_scores_one(self):
        score = self.judge.score_prediction(0.0, 0.0, "flat", "flat")
        assert score == 1.0

    def test_predicted_flat_but_moved(self):
        """Predicted flat but market moved — partial credit."""
        score = self.judge.score_prediction(0.0, 5.0, "flat", "up")
        assert score == 0.0  # different direction

    def test_same_direction_wrong_magnitude(self):
        """Same direction but wrong magnitude gets partial credit."""
        score = self.judge.score_prediction(10.0, 5.0, "up", "up")
        # ratio = 5/10 = 0.5, score = 0.5 + 0.5*0.5 = 0.75
        assert score == 0.75

    def test_same_direction_close_magnitude(self):
        """Within 20% gets bonus."""
        score = self.judge.score_prediction(10.0, 9.0, "up", "up")
        # ratio = 9/10 = 0.9, score = 0.5 + 0.5*0.9 = 0.95, +0.1 bonus = 1.0
        assert score == 1.0

    def test_actual_exceeds_predicted(self):
        """Actual movement exceeds prediction."""
        score = self.judge.score_prediction(5.0, 10.0, "up", "up")
        # ratio = 5/10 = 0.5, score = 0.5 + 0.5*0.5 = 0.75
        assert score == 0.75


class TestJudgeOutcomeOnly:
    def setup_method(self):
        self.judge = AdversarialJudge(persist=False)

    def test_price_anchored_scoring(self):
        """When price data is present, use price-anchored scoring."""
        outcome = {
            "predicted_price_delta_pct": 5.0,
            "actual_price_delta_pct": 5.0,
            "current_price": 100.0,
            "resolution_price": 105.0,
        }
        verdict = self.judge.judge_outcome_only(1, {"recommended_action": "accumulate"}, outcome)
        assert verdict["scoring_mode"] == "price"
        assert verdict["score"] == 1.0

    def test_fallback_to_metadata(self):
        """When no price data, fall back to metadata scoring."""
        outcome = {
            "emission": 2.0,
            "social_mentions": 500,
            "status": "active",
            "is_overvalued": False,
        }
        verdict = self.judge.judge_outcome_only(1, {"recommended_action": "accumulate"}, outcome)
        assert verdict["scoring_mode"] == "metadata"
        assert verdict["score"] > 0.5  # Should be favorable for accumulate + good metrics

    def test_metadata_reduce_overvalued(self):
        outcome = {
            "emission": 0.5,
            "social_mentions": 50,
            "status": "active",
            "is_overvalued": True,
        }
        verdict = self.judge.judge_outcome_only(1, {"recommended_action": "reduce"}, outcome)
        assert verdict["scoring_mode"] == "metadata"
        assert verdict["score"] >= 0.7  # Reduce is correct for overvalued


class TestJudgeDecision:
    def setup_method(self):
        self.judge = AdversarialJudge(persist=False)

    def test_judge_decision_uses_metadata(self):
        verdict = self.judge.judge_decision(
            {"recommended_action": "accumulate"},
            {"emission": 2.0, "social_mentions": 500, "status": "active", "is_overvalued": False},
        )
        assert verdict["scoring_mode"] == "metadata"
        assert "score" in verdict


class TestExpertAccuracy:
    def setup_method(self):
        self.judge = AdversarialJudge(persist=False)

    def test_update_expert_accuracy(self):
        self.judge.update_expert_accuracy("quant", True)
        records = self.judge.get_expert_track_records()
        assert records["quant"]["correct"] == 1
        assert records["quant"]["total"] == 1
        assert records["quant"]["accuracy"] == 1.0

    def test_multiple_updates(self):
        for _ in range(3):
            self.judge.update_expert_accuracy("quant", True)
        self.judge.update_expert_accuracy("quant", False)
        records = self.judge.get_expert_track_records()
        assert records["quant"]["correct"] == 3
        assert records["quant"]["total"] == 4
        assert records["quant"]["accuracy"] == 0.75

    def test_new_expert_initialized(self):
        self.judge.update_expert_accuracy("new_expert", True)
        records = self.judge.get_expert_track_records()
        assert "new_expert" in records
        assert records["new_expert"]["accuracy"] == 1.0