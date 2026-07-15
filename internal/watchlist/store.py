"""§17.F1 — pinned subnet watchlist (server JSON, not committed)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

WATCHLIST_PATH = os.environ.get("WATCHLIST_PATH", "data/watchlist.json")


def _default() -> Dict[str, Any]:
    return {"netuids": [], "updated_at": None}


def load_watchlist(path: Optional[str] = None) -> Dict[str, Any]:
    path = path or WATCHLIST_PATH
    try:
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            return _default()
        netuids = data.get("netuids") or []
        if not isinstance(netuids, list):
            netuids = []
        cleaned: List[int] = []
        seen = set()
        for n in netuids:
            try:
                i = int(n)
            except (TypeError, ValueError):
                continue
            if i <= 0 or i in seen:
                continue
            seen.add(i)
            cleaned.append(i)
        return {"netuids": cleaned, "updated_at": data.get("updated_at")}
    except FileNotFoundError:
        return _default()
    except Exception:
        return _default()


def save_watchlist(netuids: List[Any], path: Optional[str] = None) -> Dict[str, Any]:
    from datetime import datetime, timezone

    path = path or WATCHLIST_PATH
    cleaned: List[int] = []
    seen = set()
    for n in netuids or []:
        try:
            i = int(n)
        except (TypeError, ValueError):
            continue
        if i <= 0 or i in seen:
            continue
        seen.add(i)
        cleaned.append(i)

    payload = {
        "netuids": cleaned,
        "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(dest)
    return payload
