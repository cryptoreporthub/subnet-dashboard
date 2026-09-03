"""24h prediction resolver."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PREDICTIONS_PATH = os.path.join("data", "predictions.json")


def _save_json(path: str, data: Any, *, caller: Optional[str] = None) -> None:
    """Write JSON file atomically with caller attribution."""
    try:
        from internal.file_utils import safe_write_json
        safe_write_json(path, data)
    except Exception as exc:
        src = caller or "unknown"
        logger.warning("Failed to persist %s (source=%s): %s", os.path.basename(path), src, exc)


def fetch_prices(subnets: Optional[List[Dict[str, Any]]] = None) -> Dict[Any, float]:
    return {}


def _save_stats():
    """Placeholder for resolver stats write."""
    pass
