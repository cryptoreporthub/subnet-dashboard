"""Learning-loop health probe (Phase 0) — read-only, no scoring."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from internal.council.resolver_scheduler import (
    RESOLVER_REFRESH_MINUTES,
    get_prediction_resolver_scheduler_state,
)
from internal.council.weights import SOUL_MAP_PATH, _load_raw
from internal.learning.predictions_store import PREDICTIONS_PATH, load_predictions

SCORE_SNAPSHOTS_PATH = os.environ.get(
    "SCORE_SNAPSHOTS_PATH", os.path.join("data", "score_snapshots.json")
)
# Stall if pending work and resolver quieter than 2x refresh (default 30m).
_STALL_MULTIPLIER = 2


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _daily_pick_today(path: Optional[str] = None) -> Dict[str, Any]:
    picks_path = path or os.environ.get("DAILY_PICKS_PATH", "data/daily_picks.json")
    today = _utcnow().date().isoformat()
    out: Dict[str, Any] = {
        "date": today,
        "action": None,
        "has_pick": False,
        "pick_netuid": None,
        "reason": None,
    }
    try:
        with open(picks_path, "r", encoding="utf-8") as handle:
            records = json.load(handle)
        if not isinstance(records, list):
            return out
        for rec in reversed(records):
            if not isinstance(rec, dict) or rec.get("date") != today:
                continue
            action = str(rec.get("action") or "").upper() or None
            out["action"] = action
            out["reason"] = rec.get("reason") or rec.get("hold_reason")
            pick = rec.get("pick") if isinstance(rec.get("pick"), dict) else None
            if pick:
                out["has_pick"] = True
                netuid = pick.get("netuid")
                if netuid is None:
                    sn = pick.get("subnet") if isinstance(pick.get("subnet"), dict) else {}
                    netuid = sn.get("netuid")
                out["pick_netuid"] = netuid
            break
    except Exception:
        pass
    return out


def _day_ledger_present(netuid: Any, data: Optional[Dict[str, Any]] = None) -> bool:
    """True if predictions.json has a pending or resolved day row for netuid."""
    if netuid is None:
        return False
    try:
        want = int(netuid)
    except (TypeError, ValueError):
        return False
    payload = data if isinstance(data, dict) else load_predictions()
    for bucket in ("predictions", "resolved"):
        for row in payload.get(bucket) or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("horizon_type") or "hour") != "day":
                continue
            if row.get("shadow") or row.get("counterfactual"):
                continue
            try:
                if int(row.get("netuid")) == want:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _snapshot_age_seconds(path: Optional[str] = None) -> Optional[float]:
    try:
        from internal.council.score_snapshots import snapshot_age_seconds

        return snapshot_age_seconds(path or SCORE_SNAPSHOTS_PATH)
    except Exception:
        snap_path = path or SCORE_SNAPSHOTS_PATH
        try:
            mtime = os.path.getmtime(snap_path)
        except OSError:
            return None
        return max(0.0, _utcnow().timestamp() - mtime)


def _last_resolver_tick(soul_path: Optional[str] = None) -> Dict[str, Any]:
    state = get_prediction_resolver_scheduler_state()
    candidates: List[tuple] = []
    mem_at = state.get("last_run_at")
    if mem_at:
        candidates.append((_parse_iso(mem_at) or datetime.min.replace(tzinfo=timezone.utc), mem_at, state.get("last_run_ok")))
    try:
        soul = _load_raw(soul_path or SOUL_MAP_PATH)
        sched = soul.get("prediction_resolver_scheduler") or {}
        if isinstance(sched, dict):
            last = sched.get("last_cycle") or {}
            if isinstance(last, dict) and last.get("run_at"):
                run_at = last.get("run_at")
                candidates.append(
                    (
                        _parse_iso(run_at) or datetime.min.replace(tzinfo=timezone.utc),
                        run_at,
                        last.get("ok"),
                    )
                )
    except Exception:
        pass
    tick, ok = None, state.get("last_run_ok")
    if candidates:
        candidates.sort(key=lambda row: row[0], reverse=True)
        _, tick, ok = candidates[0]
    return {
        "at": tick,
        "ok": ok,
        "running": bool(state.get("running")),
        "refresh_minutes": int(
            state.get("refresh_minutes") or RESOLVER_REFRESH_MINUTES
        ),
    }


def build_learning_loop_health(
    *,
    daily_picks_path: Optional[str] = None,
    predictions_path: Optional[str] = None,
    snapshots_path: Optional[str] = None,
    soul_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Cheap JSON probe for pick→ledger→resolver loop status."""
    daily = _daily_pick_today(daily_picks_path)

    pred_path = predictions_path or PREDICTIONS_PATH
    if predictions_path:
        # Test hook: load from alternate path without mutating global.
        try:
            with open(pred_path, "r", encoding="utf-8") as handle:
                pred_data = json.load(handle)
            if not isinstance(pred_data, dict):
                pred_data = {"predictions": [], "resolved": [], "stats": {}}
        except Exception:
            pred_data = {"predictions": [], "resolved": [], "stats": {}}
    else:
        pred_data = load_predictions()

    pending_rows: List[Any] = list(pred_data.get("predictions") or [])
    pending = len(pending_rows)
    stats = pred_data.get("stats") or {}
    if isinstance(stats.get("pending"), int) and stats["pending"] >= 0:
        pending = int(stats["pending"])

    action = (daily.get("action") or "").upper()
    is_published_long = bool(
        daily.get("has_pick")
        and action
        and action not in ("HOLD", "NONE", "")
    )
    present = (
        _day_ledger_present(daily.get("pick_netuid"), pred_data)
        if is_published_long
        else False
    )
    ledger = {
        "required": is_published_long,
        "present": present if is_published_long else False,
        "gap": bool(is_published_long and not present),
        "netuid": daily.get("pick_netuid") if is_published_long else None,
    }

    resolver = _last_resolver_tick(soul_path)
    tick_at = _parse_iso(resolver.get("at"))
    refresh_m = max(1, int(resolver.get("refresh_minutes") or RESOLVER_REFRESH_MINUTES))
    stall_after_s = refresh_m * _STALL_MULTIPLIER * 60
    tick_age_s: Optional[float] = None
    if tick_at is not None:
        tick_age_s = max(0.0, (_utcnow() - tick_at).total_seconds())

    snapshot_age = _snapshot_age_seconds(snapshots_path)

    status = "ok"
    if ledger["gap"]:
        status = "stalled"
    elif pending > 0 and (
        tick_at is None or (tick_age_s is not None and tick_age_s > stall_after_s)
    ):
        status = "stalled"
    elif not resolver.get("running") or tick_at is None:
        status = "degraded"

    return {
        "status": status,
        "checked_at": _utcnow().isoformat().replace("+00:00", "Z"),
        "pending": pending,
        "last_resolver_tick": resolver.get("at"),
        "resolver": {
            "running": resolver.get("running"),
            "last_ok": resolver.get("ok"),
            "age_seconds": tick_age_s,
            "refresh_minutes": refresh_m,
        },
        "daily_pick": daily,
        "ledger": ledger,
        "snapshot_age_seconds": snapshot_age,
    }
