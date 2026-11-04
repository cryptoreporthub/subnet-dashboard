"""Shared daily-pick reader rule (plan §3)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from internal.council.pick_day import pick_day_start_utc, pick_day_str, v2_pick_id


def is_published_daily_pick_row(rec: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(rec, dict):
        return False
    if rec.get("scheduler_hold"):
        return False
    action = str(rec.get("action", "")).upper()
    if action not in ("LONG", "BUY"):
        return False
    return isinstance(rec.get("pick"), dict)


def _effective_pick_day(rec: Dict[str, Any]) -> str:
    if rec.get("pick_day"):
        return str(rec["pick_day"])
    return str(rec.get("date") or "")


def _parse_utc_instant(raw: Any) -> Optional[datetime]:
    if not raw or not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def legacy_row_write_instant(rec: Dict[str, Any]) -> Optional[datetime]:
    for key in ("build_started_at", "timestamp_utc", "selection_recorded_at_utc"):
        instant = _parse_utc_instant(rec.get(key))
        if instant is not None:
            return instant.astimezone(timezone.utc)
    return None


def legacy_row_counts_for_pick_day(rec: Dict[str, Any], pick_day: str) -> bool:
    """Legacy v1 row (no pick_id) counts for pick_day only if written at/after rollover."""
    if rec.get("pick_id"):
        return False
    if str(rec.get("date") or "") != pick_day:
        return False
    instant = legacy_row_write_instant(rec)
    if instant is None:
        return False
    return instant >= pick_day_start_utc(pick_day)


def _today_row_read_fallback(rec: Dict[str, Any]) -> bool:
    if is_published_daily_pick_row(rec):
        return True
    if rec.get("pick_id") and int(rec.get("schema_version") or 0) >= 2:
        day = pick_day_str()
        if str(rec.get("pick_day") or rec.get("date") or "") == day:
            return True
    return False


def resolve_current_daily_pick(
    records: List[Dict[str, Any]],
    *,
    now_pick_day: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Return (row, meta) per §3 reader rule."""
    pick_day = now_pick_day or pick_day_str()
    meta: Dict[str, Any] = {"pick_day": pick_day, "prior_pick_day": False}
    if not records:
        return None, meta

    target_id = v2_pick_id(pick_day)
    for rec in reversed(records):
        if rec.get("pick_id") == target_id and is_published_daily_pick_row(rec):
            return rec, meta

    v2_published_for_day = any(
        rec.get("pick_id") == target_id and is_published_daily_pick_row(rec)
        for rec in records
    )
    cutover = any(int(r.get("schema_version") or 0) >= 2 for r in records)

    best: Optional[Dict[str, Any]] = None
    best_day = ""
    for rec in records:
        if not is_published_daily_pick_row(rec):
            continue
        eff = _effective_pick_day(rec)
        if not eff or eff >= pick_day:
            if v2_published_for_day or cutover:
                if eff == pick_day and rec.get("pick_id") != target_id:
                    continue
            elif eff == pick_day:
                continue
        if eff < pick_day and eff > best_day:
            best = rec
            best_day = eff

    if best is not None:
        if _effective_pick_day(best) != pick_day:
            meta["prior_pick_day"] = True
        return best, meta
    return None, meta


def load_current_daily_pick(
    records: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Load from disk (optional records) and apply §3 reader + today fallback."""
    if records is None:
        from internal.council.daily_pick_engine import _load

        records = _load()
    row, meta = resolve_current_daily_pick(records)
    if row is not None:
        return row, meta
    from internal.council.daily_pick_engine import _find_today

    fallback = _find_today(records)
    if fallback is not None and _today_row_read_fallback(fallback):
        meta = {**meta, "fallback_today_row": True}
        return fallback, meta
    return None, meta


def find_v2_row(records: List[Dict[str, Any]], pick_day: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Latest row for v2 pick_id (published or HOLD)."""
    day = pick_day or pick_day_str()
    pid = v2_pick_id(day)
    for rec in reversed(records):
        if rec.get("pick_id") == pid:
            return rec
    return None
