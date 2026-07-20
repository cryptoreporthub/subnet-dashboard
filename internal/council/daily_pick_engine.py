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
from internal.subnets.tradable import is_tradable_subnet, subnet_netuid, tradable_subnets

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


def _payload_uses_root(payload: Dict[str, Any]) -> bool:
    """True if cached pick/candidate points at Root or a missing netuid."""
    for key in ("pick", "candidate"):
        block = payload.get(key)
        if not isinstance(block, dict):
            continue
        sn = block.get("subnet") if isinstance(block.get("subnet"), dict) else block
        if isinstance(sn, dict) and not is_tradable_subnet(sn):
            n = subnet_netuid(sn)
            if n is None or n <= 0:
                return True
    return False


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
    subnets = tradable_subnets(subnets)
    records = _load()

    if not force:
        existing = _find_today(records)
        if existing is not None and not _payload_uses_root(existing):
            # HOLD with no audited pick: attach a live candidate for display only
            # (does not change the persisted HOLD decision or invent a BUY).
            if (
                existing.get("pick") is None
                and str(existing.get("action", "")).upper() == "HOLD"
                and subnets
                and existing.get("candidate") is None
            ):
                try:
                    existing = dict(existing)
                    existing["candidate"] = select_daily_pick(subnets, market_context)
                except Exception:
                    pass
            return existing
        # Stale Root-era cache: fall through and regenerate.

    if not subnets:
        payload: Dict[str, Any] = {
            "status": "ok",
            "date": _today_str(),
            "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "action": "HOLD",
            "reason": "No subnets available",
            "pick": None,
            "candidate": None,
            "regime": classify_regime(market_context),
            "rotation_summary": get_rotation_summary(subnets),
            "market_context": market_context,
        }
        records.append(payload)
        _save(records)
        try:
            from internal.learning.prediction_loop import record_hold_decision

            record_hold_decision(reason="No subnets available", horizon_type="day")
        except Exception:
            pass
        return payload

    pick = select_daily_pick(subnets, market_context)
    final_confidence = float(pick.get("final_confidence", 0.0))

    if final_confidence < 0.45:
        action = "HOLD"
        stored_pick: Optional[Dict[str, Any]] = None
        reason = (
            f"Confidence {final_confidence:.0%} below 45% audit gate — "
            "no long call published"
        )
        candidate: Optional[Dict[str, Any]] = pick
    else:
        action = pick.get("action", "long")
        stored_pick = pick
        reason = None
        candidate = None

    payload = {
        "status": "ok",
        "date": _today_str(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "regime": classify_regime(market_context),
        "rotation_summary": get_rotation_summary(subnets),
        "action": action,
        "pick": stored_pick,
        "candidate": candidate,
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
    elif action == "HOLD":
        try:
            from internal.learning.prediction_loop import record_hold_decision

            record_hold_decision(
                candidate=candidate,
                reason=reason,
                horizon_type="day",
            )
        except Exception:
            pass

    return payload


def load_past_picks(limit: int = 7) -> List[Dict[str, Any]]:
    """Return the most recent ``limit`` daily-pick records."""
    records = _load()
    return records[-limit:] if limit else records
