"""Per-section freshness tracking for the dashboard.

A lightweight, thread-safe registry of "last updated" timestamps keyed by
dashboard section. Server code calls :func:`mark_updated` whenever a section's
data is refreshed; :func:`snapshot` returns the full map (plus the current
server time) for the ``/api/freshness`` endpoint and the frontend badges.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Dict

SECTIONS = (
    "subnets",
    "predictions",
    "top_pick_hour",
    "top_pick_day",
    "indicators",
    "simivision_picks",
    "social_sentiment",
    "rotation",
    "scenario_memory",
    "judges",
)

_lock = threading.Lock()
LAST_UPDATED: Dict[str, str] = {key: None for key in SECTIONS}


def mark_updated(key: str) -> None:
    if key not in LAST_UPDATED:
        return
    ts = datetime.now(timezone.utc).isoformat()
    with _lock:
        LAST_UPDATED[key] = ts


def snapshot() -> Dict[str, object]:
    with _lock:
        last = dict(LAST_UPDATED)
    return {
        "last_updated": last,
        "now": datetime.now(timezone.utc).isoformat(),
    }


def reset_for_tests() -> None:
    with _lock:
        for key in LAST_UPDATED:
            LAST_UPDATED[key] = None
