"""Judge weight deltas for Council Hero jury-move panel."""

from internal.learning.weight_deltas import recent_judge_weight_deltas


def test_recent_judge_weight_deltas_filters_judges(monkeypatch):
    def fake_events(limit):
        return [
            {
                "event_type": "weight_change",
                "judge": "oracle",
                "evidence": {"delta": 0.02, "dial": "oracle"},
            },
            {
                "event_type": "weight_change",
                "judge": "quant",
                "evidence": {"delta": 0.05, "dial": "quant"},
            },
            {
                "event_type": "weight_change",
                "judge": "pulse",
                "evidence": {"delta": -0.02, "dial": "pulse"},
            },
        ]

    monkeypatch.setattr(
        "internal.learning.mindmap_aggregator.collect_trail_events",
        fake_events,
    )
    deltas = recent_judge_weight_deltas()
    assert deltas == {"oracle": 0.02, "pulse": -0.02}
    assert "quant" not in deltas
