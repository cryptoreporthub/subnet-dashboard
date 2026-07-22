"""§17.U2 — compact pick story strip from §16 resolved outcomes."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_SKIP = frozenset({"duplicate", "expired", "ungradeable"})


def _is_test_fixture(pred: Dict[str, Any]) -> bool:
    """Hide dev/CI rows from the public story strip."""
    tags = pred.get("tags")
    if isinstance(tags, list):
        for tag in tags:
            if str(tag).upper() in ("TEST_CASE", "TEST", "FIXTURE"):
                return True
    statement = str(pred.get("statement") or "")
    if "TEST_CASE" in statement.upper():
        return True
    name = str(pred.get("name") or "")
    if name.upper() in ("LOL",) and "TEST" in statement.upper():
        return True
    return False


def _context_tags(pred: Dict[str, Any]) -> List[str]:
    """Plain tags from pick-time snapshot — price vs yield context (§21 L2)."""
    tags: List[str] = []
    snap = pred.get("subnet_snapshot") if isinstance(pred.get("subnet_snapshot"), dict) else {}
    if snap.get("yield_trap"):
        tags.append("yield trap")
    driver = snap.get("return_driver") or snap.get("dominant_driver")
    if driver:
        tags.append(str(driver).replace("_", " "))
    chg7 = snap.get("price_change_7d")
    if chg7 is not None:
        try:
            v = float(chg7)
            if abs(v) >= 1:
                tags.append(f"price {'up' if v > 0 else 'down'} {abs(v):.0f}% 7d")
        except (TypeError, ValueError):
            pass
    signals = pred.get("active_signals")
    if isinstance(signals, list) and signals:
        tags.append(str(signals[0]).replace("_", " "))
    out: List[str] = []
    for t in tags:
        if t and t not in out:
            out.append(t)
        if len(out) >= 3:
            break
    return out


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
            if _is_test_fixture(pred):
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
            pid = pred.get("id")
            display_name = pred.get("name") or (f"SN{netuid}" if netuid is not None else "—")
            if netuid is not None:
                try:
                    from internal.subnet_names import name_for_netuid

                    display_name = name_for_netuid(int(netuid))
                except Exception:
                    pass
            items.append(
                {
                    "id": pid,
                    "share_page_url": f"/share/call/{pid}" if pid else None,
                    "netuid": netuid,
                    "name": display_name,
                    "predicted_pct": pred.get("predicted_pct"),
                    "actual_pct": actual,
                    "outcome": "correct" if correct else "wrong",
                    "resolved_at": pred.get("resolved_at") or pred.get("created_at"),
                    "statement": pred.get("statement"),
                    "tags": [
                        t
                        for t in _context_tags(pred)
                        if str(t).upper() not in ("TEST_CASE", "TEST", "FIXTURE")
                    ],
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
