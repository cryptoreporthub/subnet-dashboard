"""The score-snapshot scheduler's last-cycle summary, kept apart from the soul_map.

The summary used to live under ``score_snapshot_scheduler.last_cycle`` inside soul_map.json. Writing
it there made every scheduler tick create the soul_map when it was missing and replace it when it
was unreadable, which turned the "weights unknown" state the snapshot gate relies on into a file of
default weights. The scheduler now writes this one small file beside the soul_map and never opens the
soul_map for writing.

Readers use ``read_last_cycle``: the new file first, then the legacy soul_map key, so a volume that
still carries only the old record (for example the first read after a deploy, or a web process
reading before the worker has ticked) keeps its in-flight and age information.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

STATE_FILENAME = "score_snapshot_scheduler.json"
LIVENESS_FILENAME = "score_snapshot_liveness.json"
_write_lock = threading.Lock()


def _soul_path(soul_map_path: Optional[str]) -> str:
    if soul_map_path:
        return soul_map_path
    from internal.council import weights

    return weights.SOUL_MAP_PATH


def scheduler_state_path(soul_map_path: Optional[str] = None) -> str:
    override = os.environ.get("SCORE_SNAPSHOT_SCHEDULER_STATE_PATH")
    if override:
        return override
    return os.path.join(os.path.dirname(_soul_path(soul_map_path)) or ".", STATE_FILENAME)


def liveness_state_path(soul_map_path: Optional[str] = None) -> str:
    """The score-snapshot liveness tracker's own file (it used to write the soul_map's ``liveness`` key)."""
    return os.path.join(os.path.dirname(_soul_path(soul_map_path)) or ".", LIVENESS_FILENAME)


def write_last_cycle(summary: Dict[str, Any], soul_map_path: Optional[str] = None) -> None:
    """Atomically replace the record. Never raises and never touches the soul_map."""
    path = scheduler_state_path(soul_map_path)
    tmp = os.path.join(os.path.dirname(path) or ".", f".{STATE_FILENAME}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with _write_lock:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            try:
                with open(tmp, "w", encoding="utf-8") as handle:
                    json.dump({"last_cycle": summary}, handle, separators=(",", ":"))
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
    except Exception as exc:
        logger.warning("score snapshot cycle summary persist failed: %s", exc)


def _read_new(soul_map_path: Optional[str]) -> Optional[Dict[str, Any]]:
    try:
        with open(scheduler_state_path(soul_map_path), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return None
    last = data.get("last_cycle") if isinstance(data, dict) else None
    return last if isinstance(last, dict) else None


def _read_legacy(soul_map_path: Optional[str]) -> Dict[str, Any]:
    try:
        from internal.council import weights

        sched = weights._load_raw(_soul_path(soul_map_path), copy_blob=False).get("score_snapshot_scheduler")
        last = sched.get("last_cycle") if isinstance(sched, dict) else None
    except Exception:
        return {}
    return dict(last) if isinstance(last, dict) else {}


def read_last_cycle(soul_map_path: Optional[str] = None) -> Dict[str, Any]:
    """The last cycle summary, ``{}`` when neither the new file nor the legacy key has one."""
    new = _read_new(soul_map_path)
    return dict(new) if new is not None else _read_legacy(soul_map_path)
