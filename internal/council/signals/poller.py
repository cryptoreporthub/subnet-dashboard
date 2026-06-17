"""
Poller Signal Worker (The Worker)

Responsible for raw data ingestion via polling within the hierarchical,
Mindmap-integrated Engine.
"""

from internal.signals.signal_tracker import SignalTracker


class PollerWorker:
    """Polls configured signal sources and records them in the pump-cycle tracker."""

    def __init__(self, tracker: SignalTracker = None):
        self.tracker = tracker or SignalTracker()

    def poll(self, asset: str, source: str, timestamp: str = None, metadata: dict = None) -> dict:
        """
        Poll a signal source and record a signal for the asset.

        In a production deployment this would connect to the actual source feed;
        for now it normalizes the incoming signal and persists it through the
        SignalTracker so the pump-cycle state machine can advance.
        """
        return self.tracker.record_signal(asset, source, timestamp, metadata)