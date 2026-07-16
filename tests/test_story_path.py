"""§21 L5 — mindmap story path cause chain."""

from internal.learning.story_path import build_story_path


def test_story_path_honest_empty_without_pick():
    out = build_story_path({"action": "HOLD", "pick": None, "candidate": None})
    assert out["data_available"] is False
    assert out["reason"] == "no_pick"
    assert out["steps"] == []


def test_story_path_five_step_chain():
    payload = {
        "action": "LONG",
        "pick": {
            "action": "long",
            "subnet": {"netuid": 8, "name": "Taoshi", "yield_trap": False},
            "reasons": ["Momentum + delegation flow"],
            "expert_contributions": {
                "quant": 0.7,
                "hype": 0.4,
                "technical": 0.5,
                "dark_horse": 0.3,
            },
            "signal_impact": {
                "active_signals": ["delegation_flow"],
                "impacts": [{"signal": "delegation_flow", "direction": "bullish"}],
            },
        },
    }
    out = build_story_path(payload)
    assert out["data_available"] is True
    assert len(out["steps"]) == 5
    ids = [s["id"] for s in out["steps"]]
    assert ids == ["signals", "judges", "council", "outcome", "weights"]
    assert "delegation" in out["steps"][0]["title"].lower() or "signal" in out["steps"][0]["title"].lower()
    assert out["steps"][2]["title"].startswith("BUY")
