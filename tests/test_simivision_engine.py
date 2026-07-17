"""Tests for SimiVision engine helpers (current API)."""


def test_generate_signals_returns_ranked_list():
    from internal.simivision.engine import generate_signals

    signals = generate_signals(top_n=5)
    assert isinstance(signals, list)
    if signals:
        row = signals[0]
        assert "netuid" in row
        assert "name" in row
        assert "conviction" in row


def test_pathfinder_worker_is_stub():
    """PathfinderWorker is a placeholder — ensure import stays stable."""
    from internal.council.signals.pathfinder import PathfinderWorker

    worker = PathfinderWorker()
    assert worker is not None
