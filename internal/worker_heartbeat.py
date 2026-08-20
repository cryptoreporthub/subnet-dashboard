"""Cross-process liveness for inline Fly worker (web + worker on one machine)."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _path() -> str:
    return os.environ.get("WORKER_HEARTBEAT_PATH", "data/.worker_heartbeat")


def touch_heartbeat() -> None:
    """Worker calls on boot and on periodic tick."""
    payload = {
        "pid": os.getpid(),
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "run_mode": os.environ.get("RUN_MODE", "worker"),
    }
    path = _path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)


def read_heartbeat() -> Optional[Dict[str, Any]]:
    try:
        with open(_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def is_alive(*, max_age_seconds: int = 120) -> bool:
    raw = read_heartbeat()
    if not raw or not raw.get("ts"):
        return False
    try:
        ts = datetime.fromisoformat(str(raw["ts"]).replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
        return age <= max_age_seconds
    except Exception:
        return False


def start_heartbeat_thread(*, interval_seconds: int = 30) -> None:
    """Periodic heartbeat for worker modes without a background scheduler (Stage 2 hop)."""

    def _beat() -> None:
        while True:
            time.sleep(interval_seconds)
            try:
                touch_heartbeat()
            except Exception as exc:
                logger.debug("heartbeat tick failed: %s", exc)

    threading.Thread(target=_beat, daemon=True, name="worker-heartbeat").start()
