"""Story strip + weight delta fixes."""

from internal.analytics.story_strip import build_story_strip
from internal.learning.weight_deltas import recent_expert_weight_deltas


def test_story_strip_refreshes_name_from_netuid(monkeypatch):
    monkeypatch.setattr(
        "internal.subnet_names.name_for_netuid",
        lambda nu: "ORO" if int(nu) == 15 else ("gm" if int(nu) == 28 else f"SN{nu}"),
    )
    monkeypatch.setattr(
        "internal.learning.predictions_store.load_predictions",
        lambda: {
            "resolved": [
                {
                    "netuid": 28,
                    "name": "LOL",
                    "actual_pct": 1.0,
                    "correct": True,
                    "outcome": "hit",
                }
            ],
            "predictions": [],
        },
    )
    out = build_story_strip(limit=5)
    assert out["items"][0]["name"] == "gm"


def test_recent_expert_weight_deltas_from_trail(monkeypatch):
    monkeypatch.setattr(
        "internal.learning.mindmap_aggregator.collect_trail_events",
        lambda limit=80: [
            {
                "event_type": "weight_change",
                "judge": "quant",
                "evidence": {"delta": 0.02},
            },
            {
                "event_type": "weight_change",
                "judge": "hype",
                "evidence": {"delta": -0.03},
            },
        ],
    )
    deltas = recent_expert_weight_deltas()
    assert deltas["quant"] == 0.02
    assert deltas["hype"] == -0.03
