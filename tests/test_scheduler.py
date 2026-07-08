"""Tests for the AdversarialScheduler state."""

from internal.scheduler import AdversarialScheduler


def test_state_includes_subnet_count():
    """State should include last_subnet_count."""
    scheduler = AdversarialScheduler(stake_threshold_tao=400000)
    state = scheduler.state()

    assert "last_subnet_count" in state
    assert state["last_subnet_count"] == 0  # Initial value
