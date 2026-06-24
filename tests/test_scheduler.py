"""Tests for the AdversarialScheduler subnet filtering."""

import pytest

from internal.scheduler import AdversarialScheduler


class TestSubnetFiltering:
    """Tests for low-mid cap subnet filtering."""

    def test_filter_excludes_high_stake_subnets(self):
        """Subnets with total_stake >= threshold should be excluded."""
        registry = {
            "0": {"staking_data": {"total_stake": 500000}},  # Excluded
            "1": {"staking_data": {"total_stake": 449999}},  # Included
            "2": {"staking_data": {"total_stake": 450000}},  # Excluded (boundary)
            "3": {"staking_data": {"total_stake": 400000}},  # Included
        }
        scheduler = AdversarialScheduler(stake_threshold_tao=450000)
        filtered = scheduler._filter_low_mid_cap_subnets(registry)
        
        assert 0 not in filtered  # Excluded
        assert 1 in filtered    # Included
        assert 2 not in filtered  # Excluded (boundary)
        assert 3 in filtered    # Included

    def test_filter_handles_missing_stake_data(self):
        """Subnets without stake data should be included (safe default)."""
        registry = {
            "0": {},  # No staking_data
            "1": {"staking_data": {}},  # Empty staking_data
            "2": {"staking_data": {"total_stake": 400000}},  # Has stake
        }
        scheduler = AdversarialScheduler(stake_threshold_tao=450000)
        filtered = scheduler._filter_low_mid_cap_subnets(registry)
        
        assert 0 in filtered
        assert 1 in filtered
        assert 2 in filtered

    def test_filter_with_custom_threshold(self):
        """Custom threshold should be respected."""
        registry = {
            "0": {"staking_data": {"total_stake": 300000}},
            "1": {"staking_data": {"total_stake": 200000}},
        }
        scheduler = AdversarialScheduler(stake_threshold_tao=250000)
        filtered = scheduler._filter_low_mid_cap_subnets(registry)
        
        assert 0 not in filtered  # 300k >= 250k threshold
        assert 1 in filtered    # 200k < 250k threshold

    def test_state_includes_subnet_count(self):
        """State should include last_subnet_count."""
        scheduler = AdversarialScheduler(stake_threshold_tao=450000)
        state = scheduler.state()
        
        assert "last_subnet_count" in state
        assert state["last_subnet_count"] == 0  # Initial value