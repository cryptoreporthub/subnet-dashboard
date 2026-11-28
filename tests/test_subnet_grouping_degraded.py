"""Degraded indicator rows stay visible in subnet grouping without live signal count."""


def test_subnet_grouping_keeps_degraded_indicator_groups():
    text = open("static/js/subnet_grouping.js", encoding="utf-8").read()
    assert "hasIndicatorRows" in text
    assert "count === 0 && !hasIndicatorRows" in text
    assert "No price history" in text