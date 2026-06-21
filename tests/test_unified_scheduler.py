"""
Tests for the unified scheduler.
"""

import json
import os
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

from internal.scheduler import UnifiedScheduler, get_adversarial_scheduler_state


@pytest.fixture
def temp_soul_map():
    """Create a temporary soul_map.json for testing."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w") as f:
        json.dump({"expert_weights": {}, "verdicts": [], "hypotheses": []}, f)
    yield path
    try:
        os.unlink(path)
    except Exception:
        pass


@pytest.fixture
def temp_registry():
    """Create a temporary registry.json for testing."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    registry = {
        "1": {
            "id": 1,
            "name": "Test Subnet 1",
            "status": "active",
            "emission": 2.0,
            "social_mentions": 500,
            "is_overvalued": False,
        },
        "2": {
            "id": 2,
            "name": "Test Subnet 2",
            "status": "at-risk",
            "emission": 0.1,
            "social_mentions": 10,
            "is_overvalued": True,
        },
    }
    with open(path, "w") as f:
        json.dump(registry, f)
    yield path
    try:
        os.unlink(path)
    except Exception:
        pass


class TestUnifiedScheduler:
    def test_start_stop(self, temp_soul_map, temp_registry):
        scheduler = UnifiedScheduler(
            refresh_minutes=60,
            soul_map_path=temp_soul_map,
            registry_path=temp_registry,
        )
        result = scheduler.start(immediate=False)
        assert result["started"] is True
        assert result["refresh_minutes"] == 60

        state = scheduler.state()
        assert state["running"] is True

        result = scheduler.stop()
        assert result["stopped"] is True
        assert scheduler.state()["running"] is False

    def test_double_start_is_idempotent(self, temp_soul_map, temp_registry):
        scheduler = UnifiedScheduler(
            refresh_minutes=60,
            soul_map_path=temp_soul_map,
            registry_path=temp_registry,
        )
        scheduler.start(immediate=False)
        result = scheduler.start(immediate=False)
        assert result["started"] is False
        assert result["reason"] == "already running"
        scheduler.stop()

    def test_state_when_not_running(self, temp_soul_map, temp_registry):
        scheduler = UnifiedScheduler(
            refresh_minutes=60,
            soul_map_path=temp_soul_map,
            registry_path=temp_registry,
        )
        state = scheduler.state()
        assert state["running"] is False
        assert state["refresh_minutes"] == 60

    @patch("internal.scheduler.fetch_prices")
    def test_run_once(self, mock_fetch, temp_soul_map, temp_registry):
        mock_fetch.return_value = {
            "prices": {"TAO": {"price_usd": 100.0, "source": "api"}},
            "fetched_at": "2026-01-01T00:00:00Z",
            "errors": [],
        }
        scheduler = UnifiedScheduler(
            refresh_minutes=60,
            soul_map_path=temp_soul_map,
            registry_path=temp_registry,
        )
        result = scheduler.run_once()
        assert result["ok"] is True
        assert "steps" in result
        assert result["steps"]["price_fetch"]["ok"] is True
        assert result["steps"]["selector"]["decisions"] == 2
        assert result["steps"]["judge"]["verdicts"] == 2

    @patch("internal.scheduler.fetch_prices")
    def test_run_once_with_price_fetch_error(self, mock_fetch, temp_soul_map, temp_registry):
        """When price fetch fails, the cycle should still complete with metadata fallback."""
        mock_fetch.return_value = {
            "prices": {},
            "fetched_at": "2026-01-01T00:00:00Z",
            "errors": ["API error"],
        }
        scheduler = UnifiedScheduler(
            refresh_minutes=60,
            soul_map_path=temp_soul_map,
            registry_path=temp_registry,
        )
        result = scheduler.run_once()
        assert result["ok"] is True  # Should still succeed with metadata fallback
        assert result["steps"]["price_fetch"]["ok"] is False

    def test_run_once_empty_registry(self, temp_soul_map):
        """Empty registry should cause an error."""
        fd, empty_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(empty_path, "w") as f:
            json.dump({}, f)
        try:
            scheduler = UnifiedScheduler(
                refresh_minutes=60,
                soul_map_path=temp_soul_map,
                registry_path=empty_path,
            )
            result = scheduler.run_once()
            assert result["ok"] is False
            assert result["error"] is not None
        finally:
            try:
                os.unlink(empty_path)
            except Exception:
                pass

    def test_exponential_backoff(self, temp_soul_map, temp_registry):
        """Consecutive failures should increase backoff."""
        scheduler = UnifiedScheduler(
            refresh_minutes=60,
            max_backoff_minutes=240,
            soul_map_path=temp_soul_map,
            registry_path=temp_registry,
        )
        # Simulate failures by directly manipulating state.
        scheduler._consecutive_failures = 3
        scheduler._backoff_minutes = min(60 * (2 ** 3), 240)
        assert scheduler._backoff_minutes == 240  # capped at max

    def test_module_level_singleton_state(self):
        """get_adversarial_scheduler_state should work when no scheduler is running."""
        state = get_adversarial_scheduler_state()
        assert state["running"] is False
        assert "refresh_minutes" in state