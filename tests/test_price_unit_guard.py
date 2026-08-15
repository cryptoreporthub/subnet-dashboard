from datetime import datetime, timezone

from internal.council.grading import (
    compute_actual_pct,
    is_price_unit_mismatch,
)
from internal.council.resolver import _compute_stats, resolve_prediction


def test_price_unit_guard_matches_observed_tao_usd_mismatch():
    assert is_price_unit_mismatch(0.006, 1.3)
    assert compute_actual_pct(0.006, 1.3) > 20_000


def test_price_unit_guard_allows_normal_move():
    assert not is_price_unit_mismatch(0.006, 0.007)
    assert not is_price_unit_mismatch(10.0, 210.0)


def test_mismatched_resolution_is_ungradeable_without_learning_side_effects():
    prediction = {
        "id": "unit-mismatch",
        "netuid": 1,
        "reference_price": 0.006,
        "resolve_at": datetime.now(timezone.utc).isoformat(),
        "predicted_pct": -0.4,
        "direction": "down",
    }

    resolved = resolve_prediction(prediction, current_price=1.3)

    assert resolved["outcome"] == "ungradeable"
    assert resolved["retirement_reason"] == "price_unit_mismatch"
    assert resolved["correct"] is None
    stats = _compute_stats({"predictions": [], "resolved": [resolved]})
    assert stats["correct"] == 0
    assert stats["wrong"] == 0
