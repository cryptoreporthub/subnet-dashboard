"""Expert weights: pure function of graded rows."""

from internal.learning.expert_weights import estimate_weights, wilson_interval


def _rows(expert, hits, misses, **extra):
    rows = [{"expert": expert, "outcome": "hit", **extra} for _ in range(hits)]
    rows += [{"expert": expert, "outcome": "miss", **extra} for _ in range(misses)]
    return rows


def test_interval_straddling_base_rate_keeps_weight_at_one():
    out = estimate_weights(_rows("technical", 50, 50))
    assert out["technical|unknown"]["weight"] == 1.0


def test_interval_above_base_rate_raises_weight():
    out = estimate_weights(_rows("quant", 80, 20))
    assert out["quant|unknown"]["weight"] > 1.0


def test_interval_below_base_rate_lowers_weight_and_respects_floor():
    out = estimate_weights(_rows("rogue", 20, 80))
    assert 0.25 <= out["rogue|unknown"]["weight"] < 1.0


def test_ungraded_rows_do_not_count():
    rows = _rows("hype", 10, 10) + [
        {"expert": "hype", "outcome": "ungradeable"},
        {"expert": "hype", "outcome": "duplicate"},
        {"expert": "hype", "outcome": "expired"},
    ]
    out = estimate_weights(rows)
    assert out["hype|unknown"]["n"] == 20


def test_same_rows_in_any_order_give_the_same_weights():
    rows = _rows("a", 30, 10) + _rows("b", 12, 18)
    assert estimate_weights(rows) == estimate_weights(list(reversed(rows)))


def test_small_sample_stays_near_base_rate():
    out = estimate_weights(_rows("new", 3, 0))
    assert out["new|unknown"]["weight"] == 1.0


def test_wilson_bounds_contain_the_point_estimate():
    lo, hi = wilson_interval(40, 100)
    assert lo < 0.4 < hi


def test_shadow_rows_are_not_graded():
    rows = _rows("technical", 10, 0, pick_source="council") + _rows("technical", 0, 10, pick_source="council_shadow")
    out = estimate_weights(rows)
    assert out["technical|council"]["n"] == 10
    assert "technical|council_shadow" not in out


def test_one_expert_across_sources_is_scored_per_source():
    rows = _rows("rogue", 2, 18, pick_source="pump_combined_exp") + _rows("rogue", 12, 3, pick_source="pump_lead")
    out = estimate_weights(rows)
    assert out["rogue|pump_combined_exp"]["hit_rate"] == 0.1
    assert out["rogue|pump_lead"]["hit_rate"] == 0.8
