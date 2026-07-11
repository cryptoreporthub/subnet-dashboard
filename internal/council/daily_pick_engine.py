"""
Daily pick persistence engine for the Council.

Wraps ``select_daily_pick`` with date-based caching, regime classification,
and rotation summary so the daily pick is deterministic and auditable.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.council.daily_pick import select_daily_pick
from internal.council.scenario_memory import classify_regime
from internal.council.rotation_tracker import get_rotation_summary

DAILY_PICKS_PATH = os.path.join("data", "daily_picks.json")


def _load(path: Optional[str] = None) -> List[Dict[str, Any]]:
    path = path or DAILY_PICKS_PATH
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _save(records: List[Dict[str, Any]], path: Optional[str] = None) -> None:
    path = path or DAILY_PICKS_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(records, f, indent=2)
    os.replace(tmp, path)


def _today_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _find_today(records: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    today = _today_str()
    for rec in reversed(records):
        if rec.get("date") == today:
            return rec
    return None


def get_or_create_today_pick(
    subnets: List[Dict[str, Any]],
    market_context: Optional[Dict[str, Any]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """
    Return today's daily pick, creating it if necessary.

    If ``force`` is False and a record already exists for today, the stored
    record is returned. Otherwise a new pick is generated via
    ``select_daily_pick``, optionally downgraded to HOLD when confidence is
    low, and persisted.
    """
    market_context = market_context or {}
    records = _load()

    if not force:
        existing = _find_today(records)
        if existing is not None:
            return existing

    if not subnets:
        payload: Dict[str, Any] = {
            "status": "ok",
            "date": _today_str(),
            "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "action": "HOLD",
            "reason": "No subnets available",
            "pick": None,
            "regime": classify_regime(market_context),
            "rotation_summary": get_rotation_summary(subnets),
            "market_context": market_context,
        }
        records.append(payload)
        _save(records)
        return payload

    pick = select_daily_pick(subnets, market_context)
    final_confidence = float(pick.get("final_confidence", 0.0))

    if final_confidence < 0.45:
        action = "HOLD"
        stored_pick: Optional[Dict[str, Any]] = None
        reason = "Confidence too low"
    else:
        action = pick.get("action", "long")
        stored_pick = pick
        reason = None

    payload = {
        "status": "ok",
        "date": _today_str(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "regime": classify_regime(market_context),
        "rotation_summary": get_rotation_summary(subnets),
        "action": action,
        "pick": stored_pick,
        "reason": reason,
        "market_context": market_context,
    }

    records.append(payload)
    _save(records)

    if stored_pick is not None:
        try:
            from internal.learning.prediction_loop import record_pick_prediction

            sn = stored_pick.get("subnet") if isinstance(stored_pick.get("subnet"), dict) else {}
            netuid = sn.get("netuid")
            subnet_row = next((s for s in subnets if s.get("netuid") == netuid), None)
            if subnet_row and float(subnet_row.get("price", 0) or 0) > 0:
                record_pick_prediction(
                    stored_pick,
                    subnet_row,
                    horizon_type="day",
                    market_context=market_context,
                )
        except Exception:
            pass

    return payload


def load_past_picks(limit: int = 7) -> List[Dict[str, Any]]:
    """Return the most recent ``limit`` daily-pick records."""
    records = _load()
    return records[-limit:] if limit else records
