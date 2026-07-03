import json


def test_pathfinder_weighted_consensus_uses_council_weights():
    """PathfinderWorker recomputes consensus using learned council weights."""
    from internal.council.signals.pathfinder import PathfinderWorker

    worker = PathfinderWorker()
    decision = {
        "expert_breakdown": {
            "quant": {"score": 0.9, "confidence": 0.8},
            "hype": {"score": 0.2, "confidence": 0.6},
            "dark_horse": {"score": 0.5, "confidence": 0.4},
        },
        "brain": {"action": "hold", "target_weight": 0.5, "agreement": 0.5},
    }
    worker._weights = {"quant": 0.5, "hype": 0.3, "dark_horse": 0.2}
    adjusted = worker.apply_weights(decision)
    assert "brain" in adjusted
    assert "consensus_score" in adjusted
    assert isinstance(adjusted["consensus_score"], (int, float))
    expected = round(0.9 * 0.5 + 0.2 * 0.3 + 0.5 * 0.2, 4)
    assert adjusted["consensus_score"] == expected


def test_engine_builds_signals_with_pathfinder_weights():
    """The SimiVision engine returns signals after applying pathfinder weights."""
    from internal.simivision.engine import SimiVisionEngine

    engine = SimiVisionEngine()
    signals = engine.get_signals()
    assert isinstance(signals, list)
    assert len(signals) > 0
    for signal in signals:
        assert "netuid" in signal
        assert "conviction" in signal
        assert "recommendation" in signal
