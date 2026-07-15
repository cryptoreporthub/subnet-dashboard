"""§17.U2 — compact pick story strip from §16 resolved outcomes."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_SKIP = frozenset({"duplicate", "expired", "ungradeable"})


def build_story_strip(limit: int = 8) -> Dict[str, Any]:
    """Last N gradeable resolved predictions with right/wrong labels."""
    try:
        from internal.council.grading import direction_correct
        from internal.learning.predictions_store import load_predictions

        data = load_predictions()
        items: List[Dict[str, Any]] = []
        for pred in reversed(list(data.get("resolved") or [])):
            if not isinstance(pred, dict):
                continue
            if pred.get("outcome") in _SKIP:
                continue
            actual = pred.get("actual_pct")
            if actual is None:
                continue
            correct = pred.get("correct")
            if correct is None:
                try:
                    correct = direction_correct(pred, float(actual))
                except Exception:
                    correct = None
            if correct is None:
                continue
            netuid = pred.get("netuid")
            items.append(
                {
                    "id": pred.get("id"),
                    "netuid": netuid,
                    "name": pred.get("name") or (f"SN{netuid}" if netuid is not None else "—"),
                    "predicted_pct": pred.get("predicted_pct"),
                    "actual_pct": actual,
                    "outcome": "correct" if correct else "wrong",
                    "resolved_at": pred.get("resolved_at") or pred.get("created_at"),
                    "statement": pred.get("statement"),
                }
            )
            if len(items) >= int(limit):
                break
        has_data = bool(items)
        return {
            "data_available": has_data,
            "reason": None if has_data else "no_resolved_outcomes",
            "items": items,
            "stats": {
                "correct": sum(1 for row in items if row["outcome"] == "correct"),
                "wrong": sum(1 for row in items if row["outcome"] == "wrong"),
            },
        }
    except Exception as exc:
        logger.warning("story strip build failed: %s", exc)
        return {
            "data_available": False,
            "reason": "error",
            "items": [],
            "stats": {"correct": 0, "wrong": 0},
        }
