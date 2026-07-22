"""Shared hour+day pick snapshot for cockpit.picks SSE (H1)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_AUDIT_GATE = 0.45
_last_lead_netuid: Optional[int] = None


def _emitted_at_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _generated_at_from_cache() -> str:
    try:
        from internal.council.hourly_pick import _PICK_CACHE

        ts = float(_PICK_CACHE.get("ts") or 0)
        if ts > 0:
            return (
                datetime.fromtimestamp(ts, tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )
    except Exception:
        pass
    return _emitted_at_z()


def _hour_pick_row(pick: Dict[str, Any], rank: int) -> Dict[str, Any]:
    subnet = pick.get("subnet") if isinstance(pick.get("subnet"), dict) else {}
    fc = float(pick.get("final_confidence") or pick.get("confidence") or 0)
    tags = pick.get("scenario_tags") if isinstance(pick.get("scenario_tags"), dict) else {}
    return {
        "rank": rank,
        "netuid": subnet.get("netuid") if subnet.get("netuid") is not None else pick.get("netuid"),
        "name": subnet.get("name") or pick.get("name"),
        "symbol": subnet.get("symbol") or pick.get("symbol"),
        "score": pick.get("score"),
        "confidence": pick.get("confidence"),
        "final_confidence": fc,
        "action": pick.get("action", "long"),
        "audited": fc >= _AUDIT_GATE,
        "horizon": "1h",
        "generated_at": pick.get("generated_at") or _generated_at_from_cache(),
        "reasons": pick.get("reasons") if isinstance(pick.get("reasons"), list) else [],
        "scenario_tags": tags,
    }


def _load_hour_picks() -> List[Dict[str, Any]]:
    try:
        from internal.subnets.feed import load_pick_subnets
        from internal.council.hourly_pick import select_hourly_pick
        from internal.council.weights import load_weights

        subnets = load_pick_subnets()
        if not subnets:
            return []
        ctx = {"tao_change_24h": 0.0, "weights": load_weights()}
        top = select_hourly_pick(subnets, ctx)
        if not isinstance(top, dict) or not top.get("subnet"):
            return []
        row = dict(top)
        row.setdefault("generated_at", _generated_at_from_cache())
        return [_hour_pick_row(row, 1)]
    except Exception:
        return []


def _load_day_snapshot() -> Dict[str, Any]:
    emitted_at = _emitted_at_z()
    day: Dict[str, Any] = {
        "action": "HOLD",
        "published": False,
        "reason": "No long call published",
        "date": datetime.now(timezone.utc).date().isoformat(),
        "timestamp_utc": emitted_at,
        "pick": None,
        "candidate": None,
    }
    try:
        from internal.subnets.feed import load_pick_subnets
        from internal.council.daily_pick_engine import get_or_create_today_pick
        from internal.council.weights import load_weights

        subnets = load_pick_subnets()
        if not subnets:
            return day
        ctx = {"tao_change_24h": 0.0, "weights": load_weights()}
        daily = get_or_create_today_pick(subnets, ctx)
        if not isinstance(daily, dict):
            return day
        day["action"] = str(daily.get("action") or "HOLD").upper()
        pick = daily.get("pick")
        cand = daily.get("candidate")
        day["published"] = bool(pick)
        day["pick"] = pick
        day["candidate"] = cand
        if not pick and isinstance(cand, dict):
            fc = float(cand.get("final_confidence") or cand.get("confidence") or 0)
            if fc < _AUDIT_GATE:
                day["reason"] = (
                    f"Confidence {fc * 100:.0f}% below 45% audit gate — "
                    "no long call published"
                )
            else:
                day["reason"] = "Audit blocked today's long call"
        elif daily.get("reason"):
            day["reason"] = str(daily.get("reason"))
    except Exception as exc:
        day["reason"] = str(exc)
    return day


def build_picks_snapshot() -> Dict[str, Any]:
    """Atomic hour+day snapshot for cockpit.picks SSE."""
    global _last_lead_netuid

    emitted_at = _emitted_at_z()
    hour_picks = _load_hour_picks()
    day = _load_day_snapshot()

    changed = False
    previous_lead = None
    quiet_reason = None

    lead_netuid = hour_picks[0].get("netuid") if hour_picks else None
    if lead_netuid is not None:
        try:
            lead_int = int(lead_netuid)
        except (TypeError, ValueError):
            lead_int = None
        if lead_int is not None and _last_lead_netuid is not None and lead_int != _last_lead_netuid:
            changed = True
            previous_lead = {"netuid": _last_lead_netuid, "name": f"SN{_last_lead_netuid}"}
        if lead_int is not None:
            _last_lead_netuid = lead_int
    elif not hour_picks:
        quiet_reason = "Council quiet on 1h — no name cleared the short lens"

    return {
        "type": "cockpit.picks",
        "version": 1,
        "emitted_at": emitted_at,
        "hour": {
            "picks": hour_picks,
            "meta": {
                "lens": "exploratory",
                "note": "1h watch — not today's audited 24h call",
                "changed": changed,
                "previous_lead": previous_lead,
                "quiet_reason": quiet_reason,
            },
        },
        "day": day,
    }
