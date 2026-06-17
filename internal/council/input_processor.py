"""
Input Processor Service

Responsible for parsing structured JSON intelligence and extracting subnet metadata
within the hierarchical, Mindmap-integrated Engine.
"""

import json
from typing import Any, Dict

from internal.signals.signal_tracker import SignalTracker


class InputProcessor:
    def __init__(self, tracker: SignalTracker = None):
        self.tracker = tracker or SignalTracker()

    def parse_intelligence(self, raw_json: str) -> Dict[str, Any]:
        """
        Parses structured JSON intelligence.

        Args:
            raw_json (str): The raw JSON string containing intelligence data.

        Returns:
            dict: The parsed intelligence data.
        """
        try:
            data = json.loads(raw_json)
            return data
        except json.JSONDecodeError as e:
            # In a real implementation, we would handle or log this error
            return {"error": f"Invalid JSON: {str(e)}"}

    def parse_signal_intelligence(self, raw_json: str) -> Dict[str, Any]:
        """
        Parses structured signal intelligence and records each signal.

        Args:
            raw_json (str): JSON containing either a single signal object or a
                "signals" list. Each signal needs "asset" and "source".

        Returns:
            dict: Summary of recorded signals and any errors.
        """
        data = self.parse_intelligence(raw_json)
        if "error" in data:
            return data
        results = self.tracker.ingest_intelligence(data)
        return {"recorded": len(results), "results": results}
