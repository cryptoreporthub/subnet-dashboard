import concurrent.futures
import json
import time
from unittest.mock import patch, MagicMock

import pytest

# Mock PREDICTIONS_PATH to use temp directory
PREDICTIONS_PATH = "data/predictions.json"
PREDICTIONS_LOCK_PATH = "data/predictions.json.lock"


@pytest.fixture
def temp_predictions_file(tmp_path, monkeypatch):
    """Create a temp predictions file for testing."""
    import os
    test_dir = tmp_path / "data"
    test_dir.mkdir()
    
    test_json = test_dir / "predictions.json"
    test_lock = test_dir / "predictions.json.lock"
    test_json.write_text(json.dumps({"predictions": [], "resolved": [], "stats": {"correct": 0, "wrong": 0, "pending": 0, "total": 0, "accuracy": 0.0}}))
    
    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_PATH", str(test_json))
    monkeypatch.setattr("internal.learning.predictions_store.PREDICTIONS_LOCK_PATH", str(test_lock))
    return test_json, test_lock


def test_concurrent_appends_no_collision(temp_predictions_file):
    """Test that concurrent append_predictions don't collide (Phase 5: bounded flock)."""
    test_json, test_lock = temp_predictions_file
    
    from internal.learning.predictions_store import append_prediction, load_predictions
    
    pred_a = {"id": "pred_a", "netuid": 1, "target": 100.0, "horizon_type": "hour", "status": "pending", "created_at": "2026-09-03T11:00:00Z"}
    pred_b = {"id": "pred_b", "netuid": 2, "target": 200.0, "horizon_type": "hour", "status": "pending", "created_at": "2026-09-03T11:00:00Z"}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        fut_a = executor.submit(append_prediction, pred_a)
        fut_b = executor.submit(append_prediction, pred_b)
        res_a = fut_a.result(timeout=10)
        res_b = fut_b.result(timeout=10)

    assert res_a is True
    assert res_b is True

    final_data = load_predictions()
    ids = [p["id"] for p in final_data.get("predictions", [])]
    assert "pred_a" in ids
    assert "pred_b" in ids


def test_file_lock_timeout():
    """Test that FileLockTimeout is raised when lock can't be acquired."""
    from internal.learning.predictions_store import locked_predictions_file, FileLockTimeout
    
    import tempfile
    import os
    
    # Create a temp lock file
    with tempfile.TemporaryDirectory() as tmpdir:
        lock_path = os.path.join(tmpdir, "test.lock")
        with open(lock_path, "w") as f:
            # Hold the lock in a separate process simulation
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            
            # Try to acquire with short timeout
            try:
                with locked_predictions_file(timeout_seconds=0.5):
                    assert False, "Should have timed out"
            except FileLockTimeout:
                pass  # Expected
