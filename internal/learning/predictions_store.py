"""Read/write helpers for ``data/predictions.json``."""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PREDICTIONS_PATH = os.path.join("data", "predictions.json")
PREDICTIONS_LOCK_PATH = os.path.join("data", "predictions.json.lock")


def _resolved_predictions_path(path: Optional[str] = None) -> str:
    return path or PREDICTIONS_PATH


def _predictions_lock_path(path: Optional[str] = None) -> str:
    ledger = _resolved_predictions_path(path)
    if path is None and ledger == PREDICTIONS_PATH:
        return PREDICTIONS_LOCK_PATH
    return ledger + ".lock"

_V1_TO_V2_PHASE = {
    "ACCUMULATION": "EARLY",
    "MARKUP": "EARLY",
    "PARABOLIC": "SELL",
    "DISTRIBUTION": "SELL",
    "DECLINE": "INACTIVE",
    "RE_ACCUMULATION": "CONSOLIDATING",
}


class FileLockTimeout(Exception):
    """Raised when file lock acquisition times out."""
    pass


class PredictionsLedgerUnreadable(Exception):
    """predictions.json could not be read for a write path."""

    def __init__(self, kind: str, *, error: str = "") -> None:
        super().__init__(f"{kind} predictions ledger: {error}")
        self.kind = kind
        self.error = error


class LedgerSchemaError(PredictionsLedgerUnreadable):
    def __init__(self, error: str) -> None:
        super().__init__("schema_invalid", error=error)


def parse_predictions_ledger(data: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(data)
    for bucket in ("predictions", "resolved"):
        rows = result.get(bucket, [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise LedgerSchemaError(f"{bucket} must be a list of objects")
        result[bucket] = rows
    stats = result.get("stats", _default_data()["stats"])
    if not isinstance(stats, dict):
        raise LedgerSchemaError("stats must be an object")
    result["stats"] = stats
    return result


@contextlib.contextmanager
def locked_predictions_file(timeout_seconds: float = 5.0, *, path: Optional[str] = None):
    """Cross-process advisory lock with bounded wait.

    Uses fcntl.flock for cross-process safety between web and worker processes.
    Waits up to timeout_seconds (default 5s) before raising FileLockTimeout.
    """
    lock_path = _predictions_lock_path(path)
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        deadline = time.monotonic() + timeout_seconds
        acquired = False
        while time.monotonic() < deadline:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (BlockingIOError, OSError):
                time.sleep(0.05)
        if not acquired:
            raise FileLockTimeout(
                f"Timed out after {timeout_seconds}s waiting for {lock_path}"
            )
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _default_data() -> Dict[str, Any]:
    return {
        "predictions": [],
        "resolved": [],
        "stats": {"correct": 0, "wrong": 0, "pending": 0, "total": 0, "accuracy": 0.0},
    }


def _normalize_prediction_timestamps(prediction: Dict[str, Any]) -> None:
    """Store prediction timestamps in one canonical UTC ISO-8601 format.

    Some older pick payloads contain ``...+00:00Z``.  It is readable once the
    trailing marker is handled correctly, but is not valid input for parsers
    that blindly replace ``Z`` with another offset.
    """
    for key in ("created_at", "resolve_at"):
        value = prediction.get(key)
        if value is None:
            continue
        raw = str(value).strip()
        if raw[-1:].upper() == "Z":
            raw = raw[:-1]
        try:
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            prediction[key] = parsed.astimezone(timezone.utc).isoformat().replace(
                "+00:00", "Z"
            )
        except (TypeError, ValueError):
            # Preserve genuinely corrupt values so the resolver can retire
            # them explicitly instead of silently changing their meaning.
            continue


def _migrate_expert_labels(data: Dict[str, Any]) -> bool:
    """Rename legacy contrarian expert labels to dark_horse."""
    changed = False
    for bucket in ("predictions", "resolved"):
        for pred in data.get(bucket, []) or []:
            expert = pred.get("expert")
            if isinstance(expert, str) and expert.lower().strip() == "contrarian":
                pred["expert"] = "dark_horse"
                changed = True
    return changed


def _migrate_phases(data: Dict[str, Any]) -> bool:
    changed = False
    for bucket in ("predictions", "resolved"):
        for pred in data.get(bucket, []) or []:
            phase = pred.get("phase_at_prediction")
            if phase in _V1_TO_V2_PHASE:
                pred["phase_at_prediction"] = _V1_TO_V2_PHASE[phase]
                changed = True
    return changed


def _migrate_evidence(data: Dict[str, Any]) -> bool:
    from internal.learning.evidence import stamp_evidence

    changed = False
    for bucket in ("predictions", "resolved"):
        for pred in data.get(bucket, []) or []:
            changed = stamp_evidence(pred) or changed
    return changed


def load_predictions(
    *,
    persist: bool = False,
    fail_closed: bool = False,
    path: Optional[str] = None,
) -> Dict[str, Any]:
    """Load predictions.json. Read-only callers may degrade; writers use ``fail_closed=True``."""
    from internal.store.soul_map_io import read_blob_checked

    ledger_path = _resolved_predictions_path(path)
    checked = read_blob_checked(ledger_path)
    if checked.kind in ("unreadable", "transient"):
        if fail_closed:
            raise PredictionsLedgerUnreadable(checked.kind, error=checked.error or "")
        logger.warning(
            "predictions ledger degraded read kind=%s error=%s",
            checked.kind,
            checked.error or "",
        )
        return _default_data()
    if checked.kind == "missing":
        data = _default_data()
    elif isinstance(checked.blob, dict):
        data = checked.blob
    else:
        data = _default_data()
    if not isinstance(data, dict):
        data = _default_data()
    if fail_closed:
        data = parse_predictions_ledger(data)
    else:
        data.setdefault("predictions", [])
        data.setdefault("resolved", [])
        data.setdefault("stats", _default_data()["stats"])
    changed = _migrate_phases(data)
    changed = _migrate_expert_labels(data) or changed
    changed = _migrate_evidence(data) or changed
    if changed and persist:
        save_predictions(data, path=path)
    return data


def save_predictions(
    data: Dict[str, Any],
    *,
    trigger: str = "save_predictions",
    path: Optional[str] = None,
) -> None:
    """Write predictions.json atomically with cross-process file locking.

    Uses fcntl.flock to prevent race conditions between web and worker processes.
    Lock acquisition times out after 5 seconds to avoid hanging request handlers.
    """
    from internal.ops.mutation_log import log_mutation

    ledger_path = _resolved_predictions_path(path)
    try:
        with locked_predictions_file(timeout_seconds=5.0, path=path):
            _write_predictions_unlocked(
                data,
                path=path,
                writer_function="save_predictions",
                trigger=trigger,
            )
    except FileLockTimeout:
        log_mutation(
            operation="failed",
            path=ledger_path,
            writer_function="save_predictions",
            trigger=trigger,
        )
        logger.error(
            "Failed to acquire predictions.json lock within 5s - possible deadlock or long-running write"
        )
        raise
    except Exception as exc:
        log_mutation(
            operation="failed",
            path=ledger_path,
            writer_function="save_predictions",
            trigger=trigger,
        )
        logger.warning("Failed to persist predictions.json: %s", exc)
        raise


def _write_predictions_unlocked(
    data: Dict[str, Any],
    *,
    path: Optional[str] = None,
    writer_function: str = "_write_predictions_unlocked",
    trigger: str = "save_predictions",
) -> None:
    """Atomically write predictions.json while the caller owns the file lock."""
    from internal.ops.mutation_log import log_mutation

    ledger_path = _resolved_predictions_path(path)
    log_mutation(
        operation="start",
        path=ledger_path,
        writer_function=writer_function,
        trigger=trigger,
    )
    try:
        os.makedirs(os.path.dirname(ledger_path) or ".", exist_ok=True)
        tmp = ledger_path + ".tmp"
        log_mutation(
            operation="temp-write",
            path=ledger_path,
            writer_function=writer_function,
            trigger=trigger,
        )
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        log_mutation(
            operation="rename",
            path=ledger_path,
            writer_function=writer_function,
            trigger=trigger,
        )
        os.replace(tmp, ledger_path)
        log_mutation(
            operation="completed",
            path=ledger_path,
            writer_function=writer_function,
            trigger=trigger,
        )
    except Exception:
        log_mutation(
            operation="failed",
            path=ledger_path,
            writer_function=writer_function,
            trigger=trigger,
        )
        raise


def has_pending_duplicate(
    netuid: Any,
    horizon_type: str = "hour",
    *,
    shadow: bool = False,
    path: Optional[str] = None,
) -> bool:
    """True when a pending row already exists for netuid + horizon (+ shadow flag)."""
    if netuid is None:
        return False
    want_shadow = bool(shadow)
    for existing in load_predictions(path=path).get("predictions", []) or []:
        if (
            existing.get("netuid") == netuid
            and existing.get("horizon_type", "hour") == horizon_type
            and existing.get("status") == "pending"
            and bool(existing.get("shadow") or existing.get("counterfactual")) == want_shadow
        ):
            return True
    return False


def append_prediction(
    prediction: Dict[str, Any],
    *,
    trigger: str = "append_prediction",
    path: Optional[str] = None,
) -> bool:
    """Append a pending prediction if no duplicate is already pending.

    Duplicate key: same ``netuid`` + ``horizon_type`` + shadow flag while pending.
    Returns True when the prediction was stored.
    Uses cross-process file locking to prevent concurrent write races.
    """
    if not isinstance(prediction, dict):
        return False
    from internal.learning.evidence import stamp_evidence

    _normalize_prediction_timestamps(prediction)
    stamp_evidence(prediction)
    netuid = prediction.get("netuid")
    horizon_type = prediction.get("horizon_type", "hour")
    if netuid is None:
        return False
    shadow = bool(prediction.get("shadow") or prediction.get("counterfactual"))

    with locked_predictions_file(timeout_seconds=5.0, path=path):
        data = load_predictions(fail_closed=True, path=path)
        pending = data.get("predictions", [])
        for existing in pending:
            if (
                existing.get("netuid") == netuid
                and existing.get("horizon_type", "hour") == horizon_type
                and existing.get("status") == "pending"
                and bool(existing.get("shadow") or existing.get("counterfactual")) == shadow
            ):
                return False

        pending.append(prediction)
        data["predictions"] = pending
        update_stats(data)
        _write_predictions_unlocked(
            data,
            path=path,
            writer_function="append_prediction",
            trigger=trigger,
        )
    return True


def update_stats(data: Dict[str, Any]) -> None:
    preds: List[Dict[str, Any]] = data.get("predictions", [])
    resolved: List[Dict[str, Any]] = data.get("resolved", [])

    def _primary(row: Dict[str, Any]) -> bool:
        return not bool(row.get("shadow") or row.get("counterfactual"))

    primary_resolved = [row for row in resolved if _primary(row)]
    primary_pending = [row for row in preds if _primary(row)]
    correct = sum(1 for row in primary_resolved if row.get("correct") is True)
    wrong = sum(1 for row in primary_resolved if row.get("correct") is False)
    stats = {
        "correct": correct,
        "wrong": wrong,
        "pending": len(primary_pending),
        "total": len(primary_pending) + len(primary_resolved),
    }
    if correct + wrong > 0:
        stats["accuracy"] = round(correct / (correct + wrong), 3)
    else:
        stats["accuracy"] = 0.0
    data["stats"] = stats


def count_unclassified(data: Optional[Dict[str, Any]] = None) -> int:
    """Count ledger rows tagged expert=unclassified (pending + resolved)."""
    if data is None:
        data = load_predictions()
    if not isinstance(data, dict):
        return 0
    n = 0
    for bucket in ("predictions", "resolved"):
        for row in data.get(bucket) or []:
            if isinstance(row, dict) and str(row.get("expert") or "").lower() == "unclassified":
                n += 1
    return n
