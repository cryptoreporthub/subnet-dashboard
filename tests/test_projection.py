"""
Tests for the Council projection module.
"""

import json
import os
import tempfile
import pytest

from internal.council import trace_store as trace_module
from internal.council.projection import (
    rebuild_soul_map,
    maybe_rebuild_soul_map,
    get_soul_map_projection,
    set_store,
)


@pytest.fixture
def temp_paths(tmp_path, monkeypatch):
    """Set up temporary paths for testing."""
    db_path = str(tmp_path / "council_trace.db")
    soul_map_path = str(tmp_path / "soul_map.json")
    
    # Reset singleton and create new store with temp path
    trace_module._TraceStore__instance = None
    store = trace_module.TraceStore(db_path)
    
    # Set the store in projection module
    set_store(store)
    
    return {"db_path": db_path, "soul_map_path": soul_map_path, "store": store}


def test_rebuild_soul_map_creates_file(temp_paths):
    """Test that rebuild_soul_map creates a soul_map.json file."""
    result = rebuild_soul_map(temp_paths["soul_map_path"])
    
    assert os.path.exists(temp_paths["soul_map_path"])
    assert "expert_weights" in result
    assert "performance_history" in result
    assert "council_dispositions" in result
    assert "council" in result
    assert "last_updated" in result


def test_rebuild_soul_map_with_learning_updates(temp_paths):
    """Test that rebuild_soul_map includes learning updates."""
    store = temp_paths["store"]
    
    # Add some learning updates
    store.add_learning_update(
        run_id=None,
        expert="quant",
        old_weight=1.0,
        new_weight=1.05,
    )
    store.add_learning_update(
        run_id=None,
        expert="hype",
        old_weight=1.0,
        new_weight=0.95,
    )
    
    result = rebuild_soul_map(temp_paths["soul_map_path"])
    
    assert result["expert_weights"]["quant"] == 1.05
    assert result["expert_weights"]["hype"] == 0.95


def test_rebuild_soul_map_with_runs(temp_paths):
    """Test that rebuild_soul_map includes run data."""
    store = temp_paths["store"]
    
    # Add some runs
    store.create_run(
        subnet_id=1,
        subnet_name="TestSubnet",
        horizon="day",
        total_score=75.0,
        confidence=0.85,
    )
    store.create_run(
        subnet_id=2,
        subnet_name="AnotherSubnet",
        horizon="day",
        total_score=60.0,
        confidence=0.70,
    )
    
    result = rebuild_soul_map(temp_paths["soul_map_path"])
    
    assert result["performance_history"]["total_records"] == 2


def test_maybe_rebuild_soul_map_creates_if_missing(temp_paths):
    """Test that maybe_rebuild_soul_map creates if file missing."""
    result = maybe_rebuild_soul_map(temp_paths["soul_map_path"])
    
    assert result is True
    assert os.path.exists(temp_paths["soul_map_path"])


def test_maybe_rebuild_soul_map_no_rebuild_if_current(temp_paths):
    """Test that maybe_rebuild_soul_map skips if already current."""
    # Create initial soul_map
    rebuild_soul_map(temp_paths["soul_map_path"])
    
    # Should not rebuild
    result = maybe_rebuild_soul_map(temp_paths["soul_map_path"])
    
    assert result is False


def test_maybe_rebuild_soul_map_rebuilds_if_trace_newer(temp_paths):
    """Test that maybe_rebuild_soul_map rebuilds if trace is newer."""
    store = temp_paths["store"]
    
    # Create initial soul_map
    rebuild_soul_map(temp_paths["soul_map_path"])
    
    # Add a new run to trace
    store.create_run(
        subnet_id=1,
        subnet_name="NewSubnet",
        horizon="day",
        total_score=80.0,
    )
    
    # Should rebuild
    result = maybe_rebuild_soul_map(temp_paths["soul_map_path"])
    
    assert result is True


def test_get_soul_map_projection(temp_paths):
    """Test getting the soul map projection."""
    # Add some data
    store = temp_paths["store"]
    store.create_run(subnet_id=1, total_score=75.0)
    
    result = get_soul_map_projection()
    
    assert "expert_weights" in result
    assert "last_updated" in result


def test_soul_map_structure(temp_paths):
    """Test that soul_map has the expected structure."""
    result = rebuild_soul_map(temp_paths["soul_map_path"])
    
    # Check expert_weights
    assert isinstance(result["expert_weights"], dict)
    for expert in ["quant", "hype", "contrarian", "technical"]:
        assert expert in result["expert_weights"]
        assert isinstance(result["expert_weights"][expert], (int, float))
    
    # Check performance_history
    assert isinstance(result["performance_history"], dict)
    assert "accuracy" in result["performance_history"]
    assert "total_records" in result["performance_history"]
    
    # Check council_dispositions
    assert isinstance(result["council_dispositions"], dict)
    
    # Check council
    assert isinstance(result["council"], dict)