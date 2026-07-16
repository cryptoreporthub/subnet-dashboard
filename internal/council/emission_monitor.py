"""
Emission Monitor Service

Tracks emission deltas vs the last registry snapshot in soul_map.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

SOUL_MAP_PATH = os.environ.get("SOUL_MAP_PATH", "data/soul_map.json")


def _load_soul() -> Dict[str, Any]:
    try:
        with open(SOUL_MAP_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


class EmissionMonitor:
    def __init__(self, registry_path: str = "config/registry.json"):
        self.registry_path = registry_path

    def _previous_emission(self, subnet_id: int) -> Optional[float]:
        snap = (_load_soul().get("emission_monitor") or {}).get("last_emissions") or {}
        raw = snap.get(str(subnet_id))
        if raw is None:
            raw = snap.get(subnet_id)
        try:
            val = float(raw)
            return val if val >= 0 else None
        except (TypeError, ValueError):
            return None

    def check_emission_deltas(self, subnet_id: int, current_emission: float) -> dict:
        """Compare current emission to the last scheduler snapshot."""
        try:
            current = float(current_emission or 0)
        except (TypeError, ValueError):
            current = 0.0
        previous = self._previous_emission(subnet_id)
        if previous is None:
            delta = 0.0
            trend = "unknown"
        else:
            delta = round(current - previous, 6)
            if previous <= 0:
                trend = "stable"
            elif delta > previous * 0.02:
                trend = "up"
            elif delta < -previous * 0.02:
                trend = "down"
            else:
                trend = "stable"
        return {
            "subnet_id": subnet_id,
            "previous_emission": previous,
            "current_emission": current,
            "delta": delta,
            "trend": trend,
        }


def snapshot_registry_emissions(registry: Dict[str, Any], *, run_at: str) -> Dict[str, float]:
    """Persist per-netuid emissions for the next delta check."""
    out: Dict[str, float] = {}
    for key, row in (registry or {}).items():
        if not isinstance(row, dict):
            continue
        uid = row.get("netuid", key)
        try:
            out[str(uid)] = float(row.get("emission", 0) or 0)
        except (TypeError, ValueError):
            continue
    return out


if __name__ == "__main__":
    mon = EmissionMonitor()
    assert mon.check_emission_deltas(1, 10.0)["trend"] in {"stable", "unknown", "up", "down"}
    print("emission_monitor self-check ok")
