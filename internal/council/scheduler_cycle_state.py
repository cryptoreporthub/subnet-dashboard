"""The score-snapshot scheduler's last-cycle summary, kept apart from the soul_map.

The summary used to live under ``score_snapshot_scheduler.last_cycle`` inside soul_map.json. Writing
it there made every scheduler tick create the soul_map when it was missing and replace it when it
was unreadable, which turned the "weights unknown" state the snapshot gate relies on into a file of
default weights. The scheduler now writes this one small file beside the soul_map and never opens the
soul_map for writing.

Readers use ``read_last_cycle``: the new file first, then the legacy soul_map key, so a volume that
still carries only the old record (for example the first read after a deploy, or a web process
reading before the worker has ticked) keeps its in-flight and age information.

A present-but-empty ``last_cycle`` object (``{}``) is **unreadable**, same on the new file and
legacy soul_map key. Field typing: ``phase`` may be absent, JSON null, or a string; ``run_id`` and
``progress`` may be absent, JSON null, or a string.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import threading
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

STATE_FILENAME = "score_snapshot_scheduler.json"
LIVENESS_FILENAME = "score_snapshot_liveness.json"
_write_lock = threading.Lock()


class CycleStateUnreadableError(Exception):
    """The on-disk cycle state file exists but cannot be read or parsed."""


def _last_cycle_summary_unreadable(last: Dict[str, Any], path: str, *, channel: str) -> bool:
    """Validate ``last_cycle`` field types when the value is a JSON object.

    Empty ``{}`` is unreadable (no cycle summary; new and legacy readers agree).

    ``phase`` may be absent, JSON null (legacy writers), or a string. ``run_id`` and ``progress``
    may be absent, JSON null (identity-less), or a string. Any other type → unreadable.
    """
    if not last:
        logger.warning(
            "score snapshot %s cycle state malformed (%s): last_cycle is empty",
            channel,
            path,
        )
        return True
    if "phase" in last:
        phase = last["phase"]
        if phase is not None and not isinstance(phase, str):
            logger.warning(
                "score snapshot %s cycle state malformed (%s): phase has wrong type",
                channel,
                path,
            )
            return True
    for key in ("run_id", "progress"):
        if key not in last:
            continue
        val = last[key]
        if val is not None and not isinstance(val, str):
            logger.warning(
                "score snapshot %s cycle state malformed (%s): %s has wrong type",
                channel,
                path,
                key,
            )
            return True
    return False


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


def _read_new(soul_map_path: Optional[str]) -> tuple[Optional[Dict[str, Any]], bool]:
    """Read the new cycle-state file.

    Returns ``(summary, unreadable)``. ``unreadable`` is True when the file exists but
    cannot be read or parsed; ``summary`` is None when the file is absent or has no
    ``last_cycle`` record (distinct from unreadable).
    """
    path = scheduler_state_path(soul_map_path)
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None, False
    except PermissionError as exc:
        logger.warning("score snapshot cycle state unreadable (%s): %s", path, exc)
        return None, True
    except OSError as exc:
        logger.warning("score snapshot cycle state unreadable (%s): %s", path, exc)
        return None, True
    if not stat.S_ISREG(st.st_mode):
        logger.warning("score snapshot cycle state unreadable (%s): not a regular file", path)
        return None, True
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("score snapshot cycle state unreadable (%s): %s", path, exc)
        return None, True
    if not raw.strip():
        logger.warning("score snapshot cycle state unreadable (%s): empty file", path)
        return None, True
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("score snapshot cycle state malformed (%s): %s", path, exc)
        return None, True
    if not isinstance(data, dict):
        logger.warning("score snapshot cycle state malformed (%s): root is not an object", path)
        return None, True
    if "last_cycle" not in data:
        return None, False
    last = data["last_cycle"]
    if last is None:
        logger.warning(
            "score snapshot cycle state malformed (%s): last_cycle is null",
            path,
        )
        return None, True
    if not isinstance(last, dict):
        logger.warning("score snapshot cycle state malformed (%s): last_cycle is not an object", path)
        return None, True
    if _last_cycle_summary_unreadable(last, path, channel="cycle state"):
        return None, True
    return dict(last), False


def _read_legacy_with_status(
    soul_map_path: Optional[str],
) -> tuple[Dict[str, Any], bool]:
    """Read the legacy soul_map ``score_snapshot_scheduler.last_cycle`` record."""
    path = _soul_path(soul_map_path)
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return {}, False
    except PermissionError as exc:
        logger.warning("score snapshot legacy cycle state unreadable (%s): %s", path, exc)
        return {}, True
    except OSError as exc:
        logger.warning("score snapshot legacy cycle state unreadable (%s): %s", path, exc)
        return {}, True
    if not stat.S_ISREG(st.st_mode):
        logger.warning("score snapshot legacy cycle state unreadable (%s): not a regular file", path)
        return {}, True
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = handle.read()
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("score snapshot legacy cycle state unreadable (%s): %s", path, exc)
        return {}, True
    if not raw.strip():
        logger.warning("score snapshot legacy cycle state unreadable (%s): empty file", path)
        return {}, True
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("score snapshot legacy cycle state malformed (%s): %s", path, exc)
        return {}, True
    if not isinstance(data, dict):
        return {}, True
    if "score_snapshot_scheduler" not in data:
        return {}, False
    sched = data["score_snapshot_scheduler"]
    if sched is None:
        logger.warning(
            "score snapshot legacy cycle state malformed (%s): score_snapshot_scheduler is null",
            path,
        )
        return {}, True
    if not isinstance(sched, dict):
        return {}, True
    if "last_cycle" not in sched:
        return {}, False
    last = sched["last_cycle"]
    if last is None:
        logger.warning(
            "score snapshot legacy cycle state malformed (%s): last_cycle is null",
            path,
        )
        return {}, True
    if not isinstance(last, dict):
        logger.warning(
            "score snapshot legacy cycle state malformed (%s): last_cycle is not an object",
            path,
        )
        return {}, True
    if _last_cycle_summary_unreadable(last, path, channel="legacy cycle state"):
        return {}, True
    return dict(last), False


def _read_legacy(soul_map_path: Optional[str]) -> Dict[str, Any]:
    summary, unreadable = _read_legacy_with_status(soul_map_path)
    if unreadable:
        return {}
    return summary


def read_last_cycle_with_status(
    soul_map_path: Optional[str] = None,
) -> tuple[Dict[str, Any], str]:
    """Return ``(summary, status)`` where status is ``ok``, ``missing``, or ``unreadable``.

    When the new cycle-state file exists but is unreadable, ``summary`` still falls back to
    the legacy soul_map record (same as ``read_last_cycle``), but ``status`` remains
    ``unreadable`` so the stall-guard tick probe can treat the new file as probe-unknown.
    """
    new, unreadable = _read_new(soul_map_path)
    if unreadable:
        legacy, _leg_unread = _read_legacy_with_status(soul_map_path)
        return (legacy, "unreadable") if legacy else ({}, "unreadable")
    if new is not None:
        return dict(new), "ok"
    legacy, leg_unread = _read_legacy_with_status(soul_map_path)
    if leg_unread:
        return {}, "unreadable"
    if legacy:
        return legacy, "ok"
    return {}, "missing"


def read_last_cycle(soul_map_path: Optional[str] = None) -> Dict[str, Any]:
    """The last cycle summary, ``{}`` when neither the new file nor the legacy key has one."""
    new, _unreadable = _read_new(soul_map_path)
    if new is not None:
        return dict(new)
    legacy, unreadable = _read_legacy_with_status(soul_map_path)
    if unreadable:
        return {}
    return legacy
