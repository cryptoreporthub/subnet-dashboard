"""
Projection module to rebuild soul_map.json from the trace store.

The soul_map.json is a rebuildable projection of the canonical trace.
This module provides functions to:
- Rebuild soul_map from trace data
- Check if rebuild is needed
- Maintain the projection in sync with trace
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Import the module to allow path patching
import internal.council.trace_store as trace_module

SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")

# Global store reference (can be set for testing)
_store: Optional[Any] = None


def set_store(store: Any) -> None:
    """Set the trace store instance (for testing)."""
    global _store
    _store = store


def _get_trace_store():
    """Get the trace store instance (allows for path patching in tests)."""
    if _store is not None:
        return _store
    return trace_module.get_trace_store()


def rebuild_soul_map(soul_map_path: str = SOUL_MAP_PATH) -> Dict[str, Any]:
    """
    Rebuild soul_map.json from the trace store.
    
    Returns the rebuilt soul map data.
    """
    store = _get_trace_store()
    
    # Get all runs
    runs = store.get_recent_runs(limit=1000)
    
    # Calculate expert weights from learning updates
    expert_weights = _calculate_expert_weights(store)
    
    # Calculate performance history from runs
    performance_history = _calculate_performance_history(runs)
    
    # Calculate council dispositions
    council_dispositions = _calculate_council_dispositions(runs)
    
    # Build council state
    council = _build_council_state(runs)
    
    soul_map = {
        "expert_weights": expert_weights,
        "performance_history": performance_history,
        "council_dispositions": council_dispositions,
        "council": council,
        "last_updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    
    # Save to file
    os.makedirs(os.path.dirname(soul_map_path) or ".", exist_ok=True)
    tmp_path = soul_map_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(soul_map, f, indent=2)
    os.replace(tmp_path, soul_map_path)
    
    return soul_map


def _calculate_expert_weights(store: Any) -> Dict[str, float]:
    """Calculate current expert weights from learning updates."""
    # Start with default weights
    weights = {
        "quant": 1.0,
        "hype": 1.0,
        "contrarian": 1.0,
        "technical": 1.0,
    }
    
    # Get the latest weight for each expert
    conn = store._get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT expert, new_weight, created_at
        FROM learning_update
        WHERE new_weight IS NOT NULL
        ORDER BY created_at DESC
    """)
    
    # Track latest weight per expert
    latest_weights: Dict[str, float] = {}
    for row in cursor.fetchall():
        expert = row["expert"]
        if expert not in latest_weights:
            latest_weights[expert] = row["new_weight"]
    
    # Merge with defaults
    for expert, weight in latest_weights.items():
        if expert in weights:
            weights[expert] = weight
    
    return weights


def _calculate_performance_history(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate performance history from runs."""
    total = len(runs)
    correct = sum(1 for r in runs if r.get("total_score", 0) > 50)
    wrong = sum(1 for r in runs if r.get("total_score", 0) <= 50)
    
    accuracy = round(correct / (correct + wrong), 3) if (correct + wrong) > 0 else 0.0
    
    return {
        "accuracy": accuracy,
        "total_records": total,
        "correct": correct,
        "wrong": wrong,
        "pending": 0,
    }


def _calculate_council_dispositions(runs: List[Dict[str, Any]]) -> Dict[str, str]:
    """Calculate council dispositions from recent runs."""
    # Default dispositions
    dispositions = {
        "quant": "neutral",
        "hype": "neutral",
        "contrarian": "neutral",
        "technical": "neutral",
    }
    
    # Get recent signals to determine dispositions
    if runs:
        latest_run = runs[0]
        # This would be populated from signal records in a real implementation
        # For now, return defaults
    
    return dispositions


def _build_council_state(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build council state from runs."""
    council = {}
    
    for expert in ["quant", "hype", "contrarian", "technical"]:
        council[expert] = {
            "disposition": "neutral",
            "lens": "default",
            "pick": None,
        }
    
    return council


def maybe_rebuild_soul_map(soul_map_path: str = SOUL_MAP_PATH) -> bool:
    """
    Check if soul_map needs rebuild and do it if necessary.
    
    Returns True if rebuild was performed.
    """
    # Check if soul_map exists
    if not os.path.exists(soul_map_path):
        rebuild_soul_map(soul_map_path)
        return True
    
    # Check if trace has newer data
    try:
        store = _get_trace_store()
        runs = store.get_recent_runs(limit=1)
        
        if runs:
            # Get the latest run time
            latest_run = runs[0].get("created_at")
            
            # Get soul_map last updated
            with open(soul_map_path, "r") as f:
                soul_map = json.load(f)
            
            soul_updated = soul_map.get("last_updated")
            
            # If trace is newer, rebuild
            if latest_run and soul_updated and latest_run > soul_updated:
                rebuild_soul_map(soul_map_path)
                return True
    except Exception:
        pass
    
    return False


def get_soul_map_projection() -> Dict[str, Any]:
    """Get the current soul map projection."""
    try:
        with open(SOUL_MAP_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return rebuild_soul_map()