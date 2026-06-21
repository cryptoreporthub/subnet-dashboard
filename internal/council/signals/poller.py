"""
Signal poller — builds the learning trail for the SimiVision panel.
"""

from typing import Any, Dict, List


def build_learning_trail(refresh_minutes: int = 60) -> Dict[str, Any]:
    """
    Build the SimiVision Learning Trail panel payload.

    Returns a structured trail showing the learning loop's progress.
    """
    return {
        "refresh_minutes": refresh_minutes,
        "trail": [],
        "summary": {
            "total_cycles": 0,
            "total_verdicts": 0,
            "mean_accuracy": 0.0,
        },
    }