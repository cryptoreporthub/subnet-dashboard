"""Recoverable, at-most-once effects for committed pump grades."""

from __future__ import annotations

import fcntl
import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from enum import Enum

from internal.learning.predictions_store import (
    PersistOutcome,
    load_predictions,
    mutate_predictions,
)

logger = logging.getLogger(__name__)
BOOT_ID = str(uuid.uuid4())


class EffectClass(Enum):
    REPLAYABLE = "replayable"
    ONCE = "once"


def _pump_calibration(row):
    from internal.learning.pump_calibration import maybe_adapt_after_resolve

    return maybe_adapt_after_resolve(prediction=row)


EFFECTS = (("pump_calibration", EffectClass.ONCE, _pump_calibration),)


def pending_pump_learning(row):
    identity = row.get("id") or (row.get("netuid"), row.get("created_at"), row.get("horizon_type"))
    material = f"{identity}|{row.get('resolved_at')}|{row.get('outcome')}"
    return {
        "key": hashlib.sha256(material.encode()).hexdigest()[:16],
        "kind": "pump",
        "state": "pending",
        "owner": None,
        "done": [],
        "warnings": [],
    }


def _change_learning(path, key, expected, change):
    def mutate(data, _raw):
        for row in data["resolved"]:
            learning = row.get("learning")
            if isinstance(learning, dict) and learning.get("key") == key:
                if not expected(learning):
                    return data, [], [key]
                change(learning)
                return data, [key], []
        return data, [], [key]

    return mutate_predictions(mutate, path=path, caller="learning_effects", trigger="learning")


def reconcile_pump_learning(path, *, cycle_run_id, recovered=True):
    counts = {"applied": 0, "recovered": 0, "indeterminate": 0, "failed": 0, "busy": 0}
    data = load_predictions(path=path, fail_closed=True)
    for row in data["resolved"]:
        learning = row.get("learning")
        if not isinstance(learning, dict) or learning.get("kind") != "pump":
            continue
        if learning.get("state") == "indeterminate":
            counts["indeterminate"] += 1
            continue
        if learning.get("state") not in ("pending", "claimed"):
            continue
        key = learning["key"]
        lock_path = f"{path}.learning-{key}.lock"
        os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
        with open(lock_path, "a+", encoding="utf-8") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                counts["busy"] += 1
                continue
            try:
                fresh = load_predictions(path=path, fail_closed=True)
                current = next(
                    (r for r in fresh["resolved"] if isinstance(r.get("learning"), dict)
                     and r["learning"].get("key") == key),
                    None,
                )
                if current is None:
                    continue
                state = current["learning"]["state"]
                if state == "claimed":
                    old_owner = current["learning"].get("owner")

                    def mark_indeterminate(item):
                        item["state"] = "indeterminate"
                        item["warnings"] = ["pump_calibration may have run before interruption"]

                    outcome = _change_learning(
                        path, key,
                        lambda item: item.get("state") == "claimed" and item.get("owner") == old_owner,
                        mark_indeterminate,
                    )
                    if outcome.outcome is PersistOutcome.APPLIED:
                        counts["indeterminate"] += 1
                        logger.warning("pump learning indeterminate key=%s", key)
                    else:
                        counts["failed"] += 1
                    continue
                if state != "pending":
                    continue
                owner = {
                    "boot_id": BOOT_ID,
                    "cycle_run_id": cycle_run_id,
                    "claimed_at": datetime.now(timezone.utc).isoformat(),
                }

                def claim(item):
                    item["state"] = "claimed"
                    item["owner"] = owner

                claimed = _change_learning(path, key, lambda item: item.get("state") == "pending", claim)
                if claimed.outcome is not PersistOutcome.APPLIED:
                    counts["failed"] += 1
                    continue
                try:
                    for name, _kind, effect in EFFECTS:
                        effect(current)
                except Exception as exc:
                    def fail(item):
                        item["state"] = "indeterminate"
                        item["warnings"] = [str(exc)]

                    outcome = _change_learning(
                        path, key, lambda item: item.get("state") == "claimed" and item.get("owner") == owner,
                        fail,
                    )
                    counts["indeterminate" if outcome.outcome is PersistOutcome.APPLIED else "failed"] += 1
                    continue

                def finish(item):
                    item["done"] = [name for name, _kind, _effect in EFFECTS]
                    item["state"] = "applied"

                outcome = _change_learning(
                    path, key, lambda item: item.get("state") == "claimed" and item.get("owner") == owner,
                    finish,
                )
                if outcome.outcome is PersistOutcome.APPLIED:
                    counts["applied"] += 1
                    counts["recovered"] += int(recovered)
                else:
                    counts["failed"] += 1
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return counts
