"""Hub state persistence (overlay cache + last cycle)."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from internal.file_utils import ensure_data_dir, safe_read_json, safe_write_json

HUB_STATE_PATH = os.environ.get("SIGNAL_HUB_STATE_PATH", "data/signal_hub_state.json")


def _default_state() -> Dict[str, Any]:
    return {
        "updated_at": None,
        "last_cycle_at": None,
        "active": False,
        "trackers": [],
        "anomalies": [],
        "last_signals": [],
        "overlay": {},
        "meta": {},
    }


def load_hub_state(path: Optional[str] = None) -> Dict[str, Any]:
    path = path or HUB_STATE_PATH
    ensure_data_dir()
    raw = safe_read_json(path, _default_state())
    state = _default_state()
    state.update({k: raw.get(k) for k in state if k in raw})
    state["anomalies"] = list(raw.get("anomalies") or [])
    state["last_signals"] = list(raw.get("last_signals") or [])
    state["overlay"] = dict(raw.get("overlay") or {})
    state["meta"] = dict(raw.get("meta") or {})
    state["trackers"] = list(raw.get("trackers") or [])
    return state


def save_hub_state(patch: Dict[str, Any], path: Optional[str] = None) -> Dict[str, Any]:
    path = path or HUB_STATE_PATH
    from datetime import datetime, timezone

    state = load_hub_state(path)
    state.update(patch)
    state["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    safe_write_json(path, state)
    return state
