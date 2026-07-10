"""
Poller Signal Worker (The Worker)

Responsible for raw data ingestion via polling within the hierarchical,
Mindmap-integrated Engine.
"""

class PollerWorker:
    def __init__(self, tracker=None):
        self.tracker = tracker

    def poll(self, asset: str, source: str = "poller"):
        if self.tracker and hasattr(self.tracker, "record_signal"):
            return self.tracker.record_signal(asset, source)
        return None

    def record_signal(self, *args, **kwargs):
        if self.tracker and hasattr(self.tracker, "record_signal"):
            return self.tracker.record_signal(*args, **kwargs)
        return None