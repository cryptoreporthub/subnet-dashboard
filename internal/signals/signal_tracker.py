"""
SignalTracker — tracks signal/pump-cycle timeline for assets.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


SIGNAL_TIMELINE_PATH = os.environ.get("SIGNAL_TIMELINE_PATH", "data/signal_timeline.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_json(path: str, data: Dict[str, Any]) -> None:
    dir_name = os.path.dirname(path)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(temp, path)


class SignalTracker:
    """Tracks signals and pump-cycle state for assets."""

    def __init__(self, timeline_path: str = SIGNAL_TIMELINE_PATH):
        self.timeline_path = timeline_path
        self._data = _load_json(timeline_path)

    def get_timeline(self, asset: Optional[str] = None) -> Dict[str, Any]:
        """Return the signal timeline, optionally filtered by asset."""
        signals = self._data.get("signals", [])
        if asset:
            signals = [s for s in signals if s.get("asset", "").upper() == asset.upper()]
        return {
            "signals": signals,
            "updated_at": self._data.get("updated_at"),
            "count": len(signals),
        }

    def ingest_intelligence(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Ingest one or more signals and update pump-cycle state."""
        incoming = payload.get("signals", [payload] if "asset" in payload else [])
        results = []
        signals = self._data.get("signals", [])

        for sig in incoming:
            entry = {
                "asset": sig.get("asset", "unknown"),
                "signal_type": sig.get("signal_type", "unknown"),
                "strength": sig.get("strength", 0.5),
                "note": sig.get("note", ""),
                "timestamp": _now_iso(),
            }
            signals.append(entry)
            results.append(entry)

        # Keep last 1000 signals.
        if len(signals) > 1000:
            signals = signals[-1000:]

        self._data["signals"] = signals
        self._data["updated_at"] = _now_iso()
        _save_json(self.timeline_path, self._data)
        return results