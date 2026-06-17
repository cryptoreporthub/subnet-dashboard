"""
Pathfinder Signal Worker (The Worker)

Responsible for raw data ingestion and pathfinding within the hierarchical,
Mindmap-integrated Engine.
"""

from internal.signals.signal_tracker import SignalTracker


class PathfinderWorker:
    """Discovers signal paths and records them in the pump-cycle tracker."""

    def __init__(self, tracker: SignalTracker = None):
        self.tracker = tracker or SignalTracker()

    def route(self, asset: str, source: str, timestamp: str = None, metadata: dict = None) -> dict:
        """
        Route a discovered signal through the tracker.

        Pathfinder is responsible for identifying which asset/source combinations
        are worth tracking; the SignalTracker owns the pump-cycle state machine.
        """
        return self.tracker.record_signal(asset, source, timestamp, metadata)