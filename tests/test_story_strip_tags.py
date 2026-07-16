"""Story strip context tags (§21 L2)."""

from internal.analytics.story_strip import _context_tags, build_story_strip


def test_story_strip_includes_context_tags():
    from internal.learning.predictions_store import load_predictions

    strip = build_story_strip(limit=20)
    data = load_predictions()
    if not strip["items"]:
        pred = {
            "netuid": 8,
            "subnet_snapshot": {
                "yield_trap": True,
                "return_driver": "yield_trap",
                "price_change_7d": -8.0,
            },
            "active_signals": ["macd_cross"],
        }
        assert "yield trap" in _context_tags(pred)
        return
    for item in strip["items"]:
        assert "tags" in item
        assert isinstance(item["tags"], list)
