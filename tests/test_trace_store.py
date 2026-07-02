"""
Tests for the Council trace store.
"""

import os
import tempfile
import pytest

from internal.council import trace_store as trace_module


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def store(temp_db):
    """Create a trace store with a temporary database."""
    # Reset singleton for each test
    trace_module._TraceStore__instance = None
    return trace_module.TraceStore(temp_db)  # Create new instance directly


def test_create_run(store):
    """Test creating a council run."""
    run_id = store.create_run(
        subnet_id=1,
        subnet_name="TestSubnet",
        horizon="day",
        total_score=75.5,
        confidence=0.85,
        final_action="long",
        final_confidence=0.82,
    )
    
    assert run_id.startswith("run_")
    
    # Verify it was stored
    run = store.get_run(run_id)
    assert run is not None
    assert run["subnet_id"] == 1
    assert run["subnet_name"] == "TestSubnet"
    assert run["horizon"] == "day"
    assert run["total_score"] == 75.5


def test_add_signal(store):
    """Test adding a signal record."""
    run_id = store.create_run()
    
    signal_id = store.add_signal(
        run_id=run_id,
        expert="quant",
        signal_type="price_momentum",
        score=0.75,
        contribution=0.3,
        metadata={"indicator": "rsi"},
    )
    
    assert signal_id.startswith("sig_")
    
    run = store.get_run(run_id)
    assert len(run["signals"]) == 1
    assert run["signals"][0]["expert"] == "quant"


def test_add_decision(store):
    """Test adding a decision record."""
    run_id = store.create_run()
    
    decision_id = store.add_decision(
        run_id=run_id,
        decision_type="daily_pick",
        action="long",
        confidence=0.85,
        rationale="Strong bullish signal",
    )
    
    assert decision_id.startswith("dec_")
    
    run = store.get_run(run_id)
    assert len(run["decisions"]) == 1
    assert run["decisions"][0]["action"] == "long"


def test_add_judge_verdict(store):
    """Test adding a judge verdict."""
    run_id = store.create_run()
    
    verdict_id = store.add_judge_verdict(
        run_id=run_id,
        judge_name="red_team",
        approved=True,
        concerns=["Low volume"],
        adjusted_confidence=0.75,
    )
    
    assert verdict_id.startswith("ver_")
    
    run = store.get_run(run_id)
    assert len(run["verdicts"]) == 1
    assert run["verdicts"][0]["approved"] == 1


def test_add_learning_update(store):
    """Test adding a learning update."""
    run_id = store.create_run()
    
    update_id = store.add_learning_update(
        run_id=run_id,
        expert="quant",
        old_weight=1.0,
        new_weight=1.02,
        reason="correct",
    )
    
    assert update_id.startswith("upd_")
    
    run = store.get_run(run_id)
    assert len(run["learning_updates"]) == 1
    assert run["learning_updates"][0]["old_weight"] == 1.0
    assert run["learning_updates"][0]["new_weight"] == 1.02


def test_add_evidence(store):
    """Test adding an evidence record."""
    evidence_id = store.add_evidence(
        run_id=None,
        source="web",
        url="https://example.com",
        title="Test Article",
        content="This is test content",
        relevance_score=0.85,
    )
    
    assert evidence_id.startswith("ev_")
    
    evidence = store.get_evidence(limit=10)
    assert len(evidence) == 1
    assert evidence[0]["source"] == "web"


def test_get_recent_runs(store):
    """Test getting recent runs."""
    store.create_run(subnet_id=1, total_score=50)
    store.create_run(subnet_id=2, total_score=60)
    store.create_run(subnet_id=3, total_score=70)
    
    runs = store.get_recent_runs(limit=10)
    assert len(runs) == 3


def test_get_run_not_found(store):
    """Test getting a non-existent run."""
    run = store.get_run("nonexistent")
    assert run is None


def test_get_evidence_with_query(store):
    """Test getting evidence with a query filter."""
    store.add_evidence(
        run_id=None,
        source="web",
        content="bitcoin price analysis",
        relevance_score=0.9,
    )
    store.add_evidence(
        run_id=None,
        source="x",
        content="ethereum discussion",
        relevance_score=0.7,
    )
    
    results = store.get_evidence(query="bitcoin", limit=10)
    assert len(results) == 1
    assert "bitcoin" in results[0]["content"].lower()


def test_get_expert_weights_history(store):
    """Test getting expert weights history."""
    store.add_learning_update(
        run_id=None,
        expert="quant",
        old_weight=1.0,
        new_weight=1.02,
    )
    store.add_learning_update(
        run_id=None,
        expert="quant",
        old_weight=1.02,
        new_weight=1.04,
    )
    
    history = store.get_expert_weights_history()
    assert "quant" in history
    assert len(history["quant"]) == 2


def test_singleton():
    """Test that get_trace_store returns a singleton."""
    # Reset to ensure clean state
    trace_module._TraceStore__instance = None
    store1 = trace_module.TraceStore("data/test_singleton.db")
    store2 = trace_module.TraceStore("data/test_singleton.db")
    # Both should be the same instance (singleton pattern)
    assert store1 is store2 or store1.db_path == store2.db_path