"""Pick-of-the-Hour outcome tracking + success metric."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PICK_HISTORY_PATH = os.environ.get("PICK_HISTORY_PATH", os.path.join("data", "pick_history.json"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load() -> Dict[str, Any]:
    try:
        with open(PICK_HISTORY_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            data.setdefault("active", None)
            data.setdefault("history", [])
            return data
    except Exception:
        pass
    return {"active": None, "history": []}


def _save(data: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(PICK_HISTORY_PATH) or "data", exist_ok=True)
        with open(PICK_HISTORY_PATH, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
    except Exception as exc:
        logger.warning("pick_history save failed: %s", exc)


def _retire_active(store: Dict[str, Any], *, reason: str) -> None:
    active = store.get("active")
    if not isinstance(active, dict) or active.get("finalized"):
        return
    active = dict(active)
    active["finalized"] = True
    active["success"] = None
    active["outcome"] = reason
    active["resolved_at"] = _now_iso()
    store.setdefault("history", []).insert(0, active)
    store["active"] = None


def record_hour_pick(
    pick: Dict[str, Any],
    subnet: Dict[str, Any],
    *,
    prediction_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Track the #1 hour pick entry price; links to learning-loop prediction id."""
    if not isinstance(pick, dict) or not isinstance(subnet, dict):
        return None
    netuid = subnet.get("netuid") or pick.get("netuid")
    if netuid is None:
        return None
    try:
        entry_price = float(subnet.get("price", 0) or 0)
    except (TypeError, ValueError):
        entry_price = 0.0
    if entry_price <= 0:
        return None

    store = _load()
    _retire_active(store, reason="replaced")

    row = {
        "netuid": netuid,
        "name": pick.get("name") or subnet.get("name") or f"SN{netuid}",
        "entry_price": entry_price,
        "picked_at": _now_iso(),
        "prediction_id": prediction_id,
        "direction": pick.get("direction") or pick.get("action"),
        "confidence": pick.get("confidence", pick.get("final_confidence")),
        "finalized": False,
    }
    store["active"] = row
    _save(store)
    return row


def finalize_from_prediction(prediction: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Move active hour pick to history when its prediction resolves."""
    if not isinstance(prediction, dict):
        return None
    if str(prediction.get("horizon_type") or "") != "hour":
        return None

    store = _load()
    active = store.get("active")
    if not isinstance(active, dict) or active.get("finalized"):
        return None

    pred_id = prediction.get("id")
    if pred_id and active.get("prediction_id"):
        if str(active["prediction_id"]) != str(pred_id):
            return None
    elif active.get("netuid") != prediction.get("netuid"):
        return None

    row = dict(active)
    row["finalized"] = True
    row["resolved_at"] = prediction.get("resolved_at") or _now_iso()
    row["exit_price"] = prediction.get("resolved_price")
    row["actual_pct"] = prediction.get("actual_pct")
    correct = prediction.get("correct")
    row["success"] = bool(correct) if correct is not None else None
    row["outcome"] = prediction.get("outcome")

    store.setdefault("history", []).insert(0, row)
    store["active"] = None
    _save(store)
    return row


def get_history(limit: int = 20) -> Dict[str, Any]:
    """Return the active pick, recent finalized history, and aggregate stats."""
    store = _load()
    history: List[Dict[str, Any]] = list(store.get("history") or [])
    finalized = [row for row in history if isinstance(row, dict) and row.get("finalized")]
    graded = [row for row in finalized if row.get("success") is not None]
    total = len(graded)
    wins = sum(1 for row in graded if row.get("success"))
    success_rate = round(wins / total * 100.0, 1) if total else 0.0
    return {
        "active": store.get("active"),
        "history": finalized[:limit],
        "stats": {
            "total": total,
            "wins": wins,
            "losses": total - wins,
            "success_rate": success_rate,
        },
    }


if __name__ == "__main__":
    store_path = "/tmp/pick_history_selfcheck.json"
    os.environ["PICK_HISTORY_PATH"] = store_path
    rec = record_hour_pick(
        {"confidence": 0.8, "action": "long"},
        {"netuid": 1, "name": "Alpha", "price": 100.0},
        prediction_id="p1",
    )
    assert rec and rec["netuid"] == 1
    fin = finalize_from_prediction(
        {
            "id": "p1",
            "horizon_type": "hour",
            "netuid": 1,
            "correct": True,
            "outcome": "hit",
            "actual_pct": 2.0,
            "resolved_price": 102.0,
        }
    )
    assert fin and fin["success"] is True
    stats = get_history()
    assert stats["stats"]["wins"] == 1
    print("pick_history self-check ok")
