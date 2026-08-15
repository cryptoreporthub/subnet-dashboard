import math

from internal.judges.grading import judge_nudge_magnitude_scale
from internal.judges.replay import normalized_entropy, replay_divergence_report, replay_judge_weights
from internal.judges.weights import load_judge_weights, nudge_judge


def test_magnitude_scale_small_hit_rewards_less():
    pred = {"direction": "up", "predicted_pct": 5.0}
    assert judge_nudge_magnitude_scale(pred, actual_pct=0.2, correct=True) < 1.0


def test_magnitude_scale_big_hit_rewards_more():
    pred = {"direction": "up", "predicted_pct": 2.0}
    scale = judge_nudge_magnitude_scale(pred, actual_pct=8.0, correct=True)
    assert scale > 1.0
    assert scale <= 1.0 + math.log(3.0)


def test_magnitude_scale_miss_floors_at_one():
    pred = {"direction": "up", "predicted_pct": 5.0}
    assert judge_nudge_magnitude_scale(pred, actual_pct=0.1, correct=False) == 1.0


def test_magnitude_scale_uses_judge_conviction():
    pred = {
        "direction": "up",
        "predicted_pct": 2.0,
        "judge_scores_at_creation": {
            "oracle": {"score": 0.56},
            "pulse": {"score": 0.95},
        },
    }
    near_threshold = judge_nudge_magnitude_scale(pred, 8.0, True, "oracle")
    high_conviction = judge_nudge_magnitude_scale(pred, 8.0, True, "pulse")
    assert high_conviction > near_threshold


def test_nudge_judge_applies_magnitude_scale(tmp_path):
    soul_path = tmp_path / "soul_map.json"
    before = load_judge_weights(path=str(soul_path))["oracle"]
    after = nudge_judge("oracle", True, path=str(soul_path), scale=2.0)
    assert after == round(before + 0.04, 4)


def test_replay_selective_grading_diverges_judges():
    rows = [
        {
            "direction": "up",
            "predicted_pct": 3.0,
            "actual_pct": -2.0,
            "status": "resolved",
            "judge_scores_at_creation": {
                "oracle": {"score": 0.8},
                "echo": {"score": 0.45},
                "pulse": {"score": 0.6},
            },
        },
        {
            "direction": "up",
            "predicted_pct": 4.0,
            "actual_pct": 5.0,
            "status": "resolved",
            "judge_scores_at_creation": {
                "oracle": {"score": 0.9},
                "echo": {"score": 0.4},
                "pulse": {"score": 0.7},
            },
        },
    ]
    report = replay_divergence_report(rows)
    assert report["sample_size"] == 2
    assert report["flat_spread"] > 0
    assert report["flat_entropy"] > 0
    assert report["magnitude_spread"] >= report["flat_spread"]


def test_magnitude_replay_spreads_more_than_flat_on_varied_moves():
    rows = [
        {
            "direction": "up",
            "predicted_pct": 1.0,
            "actual_pct": 0.1,
            "status": "resolved",
            "judge_scores_at_creation": {"oracle": {"score": 0.9}},
        },
        {
            "direction": "up",
            "predicted_pct": 1.0,
            "actual_pct": 6.0,
            "status": "resolved",
            "judge_scores_at_creation": {"oracle": {"score": 0.9}},
        },
    ]
    flat = replay_judge_weights(rows, magnitude_aware=False)
    scaled = replay_judge_weights(rows, magnitude_aware=True)
    assert scaled["oracle"] > flat["oracle"]
