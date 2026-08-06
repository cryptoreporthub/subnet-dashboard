"""Council weight trend vs DEFAULT_WEIGHTS for Bench UI."""

from internal.learning.dashboard_context import _council_weights_list


def test_council_weights_trend_vs_baseline():
    graded = {"quant": 3, "hype": 2, "dark_horse": 1, "technical": 1}
    rows = _council_weights_list(
        {"quant": 1.05, "hype": 0.90, "dark_horse": 1.0, "technical": 1.002},
        expert_graded=graded,
    )
    by_name = {r["expert"]: r for r in rows}
    assert by_name["quant"]["trend"] == "up"
    assert by_name["hype"]["trend"] == "down"
    assert by_name["dark_horse"]["trend"] == "even"
    assert by_name["technical"]["trend"] == "even"
    assert "bias" not in by_name["quant"]


def test_council_weights_prior_without_graded_outcomes():
    rows = _council_weights_list(
        {"quant": 1.05, "hype": 0.90},
        expert_graded={"quant": 0, "hype": 0},
    )
    by_name = {r["expert"]: r for r in rows}
    assert by_name["quant"]["trend"] == "prior"
    assert by_name["hype"]["trend"] == "prior"


def test_council_weights_empty():
    assert _council_weights_list({}) == []
    assert _council_weights_list(None) == []
