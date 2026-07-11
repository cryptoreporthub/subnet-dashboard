"""Persist Phase B trail cursors (seen scenarios / pump phases) in analytics."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Set

CURSOR_PATH = os.environ.get("ANALYTICS_TRAIL_CURSOR_PATH", "data/analytics_trail_cursor.json")


def _load() -> Dict[str, Any]:
    try:
        with open(CURSOR_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"seen_scenario_ids": [], "pump_phases": {}}


def _save(data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(CURSOR_PATH) or ".", exist_ok=True)
    tmp = CURSOR_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, CURSOR_PATH)


def seen_scenario_ids() -> Set[str]:
    return set(_load().get("seen_scenario_ids") or [])


def mark_scenarios_seen(ids: Set[str]) -> None:
    data = _load()
    merged = set(data.get("seen_scenario_ids") or [])
    merged.update(ids)
    data["seen_scenario_ids"] = sorted(merged)[-500:]
    _save(data)


def last_pump_phases() -> Dict[str, str]:
    raw = _load().get("pump_phases") or {}
    return {str(k): str(v) for k, v in raw.items()}


def save_pump_phases(phases: Dict[str, str]) -> None:
    data = _load()
    data["pump_phases"] = phases
    _save(data)
