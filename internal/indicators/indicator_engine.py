"""
Indicator Engine — computes technical indicators from price data.
"""

import json
import os
from typing import Any, Dict, List, Optional


INDICATOR_STATE_PATH = os.environ.get("INDICATOR_STATE_PATH", "data/indicator_state.json")


def _load_json(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


class IndicatorEngine:
    """Computes and caches technical indicators for subnets."""

    def __init__(self, state_path: str = INDICATOR_STATE_PATH):
        self.state_path = state_path
        self._state = _load_json(state_path)

    def get_indicator_state(self) -> Dict[str, Any]:
        """Return current indicator state for all subnets."""
        return self._state

    def get_active_alerts(self) -> List[Dict[str, Any]]:
        """Return active crossover alerts across all subnets."""
        return self._state.get("alerts", [])