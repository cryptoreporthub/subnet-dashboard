"""Soul-map timestamp helper for proof-band weights chip."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def soul_weights_chip_context(
    *,
    soul_map_path: str = "data/soul_map.json",
    max_age_days: int = 7,
) -> Dict[str, Any]:
    """Return chip fields when soul-map weights updated recently."""
    try:
        import json

        if not os.path.exists(soul_map_path):
            return {"soul_weights_chip": None}
        with open(soul_map_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        updated_raw = (data.get("soul_map_state") or {}).get("updated_at")
        updated = _parse_iso(updated_raw)
        if updated is None:
            return {"soul_weights_chip": None}
        age_days = (datetime.now(timezone.utc) - updated.astimezone(timezone.utc)).days
        if age_days > max_age_days:
            return {"soul_weights_chip": None}
        if age_days == 0:
            ago = "today"
        elif age_days == 1:
            ago = "1d ago"
        else:
            ago = f"{age_days}d ago"
        return {"soul_weights_chip": {"ago": ago, "updated_at": updated_raw}}
    except Exception:
        return {"soul_weights_chip": None}
