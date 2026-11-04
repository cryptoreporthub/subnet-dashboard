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


def legacy_row_original_instant(rec: Dict[str, Any]) -> Optional[datetime]:
    """Immutable legacy provenance — not restampable ``build_started_at`` alone (P1-a)."""
    if rec.get("pick_id"):
        return None
    for key in ("timestamp_utc", "selection_recorded_at_utc"):
        instant = _parse_utc_instant(rec.get(key))
        if instant is not None:
            return instant.astimezone(timezone.utc)
    return None


def legacy_row_write_instant(rec: Dict[str, Any]) -> Optional[datetime]:
    original = legacy_row_original_instant(rec)
    if original is not None:
        return original
    instant = _parse_utc_instant(rec.get("build_started_at"))
    if instant is not None:
        return instant.astimezone(timezone.utc)
    return None


def legacy_row_counts_for_pick_day(rec: Dict[str, Any], pick_day: str) -> bool:
    """Legacy v1 row counts for pick_day only from immutable provenance vs rollover."""
    if rec.get("pick_id"):
        return False
    if str(rec.get("date") or "") != pick_day:
        return False
    instant = legacy_row_original_instant(rec)
    if instant is None:
        instant = _parse_utc_instant(rec.get("build_started_at"))
        if instant is not None:
            instant = instant.astimezone(timezone.utc)
    if instant is None:
        return False
    return instant >= pick_day_start_utc(pick_day)


def disk_has_v2_cutover(records: List[Dict[str, Any]]) -> bool:
    return any(int(r.get("schema_version") or 0) >= 2 or r.get("pick_id") for r in records)


def row_write_instant(rec: Dict[str, Any]) -> Optional[datetime]:
    """Best-effort creation/write time for reader ordering."""
    instant = legacy_row_write_instant(rec)
    if instant is not None:
        return instant
    return _parse_utc_instant(rec.get("timestamp_utc"))


def _today_row_read_fallback(rec: Dict[str, Any]) -> bool:
    """Published LONG/BUY only — v2 HOLD may exist on disk but is never served."""
    return is_published_daily_pick_row(rec)


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

    if not v2_published_for_day:
        same_day: Optional[Dict[str, Any]] = None
        same_stamp: Optional[datetime] = None
        for rec in records:
            if not is_published_daily_pick_row(rec):
                continue
            eff = _effective_pick_day(rec)
            if eff != pick_day:
                continue
            stamp = row_write_instant(rec)
            if same_day is None:
                same_day = rec
                same_stamp = stamp
            elif stamp is not None and (same_stamp is None or stamp > same_stamp):
                same_day = rec
                same_stamp = stamp
        if same_day is not None:
            return same_day, meta

    best: Optional[Dict[str, Any]] = None
    best_day = ""
    for rec in records:
        if not is_published_daily_pick_row(rec):
            continue
        eff = _effective_pick_day(rec)
        if not eff or eff >= pick_day:
            continue
        if eff > best_day:
            best = rec
            best_day = eff

    if best is not None:
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
    return None, meta


def find_v2_row(records: List[Dict[str, Any]], pick_day: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Latest row for v2 pick_id (published or HOLD)."""
    day = pick_day or pick_day_str()
    pid = v2_pick_id(day)
    for rec in reversed(records):
        if rec.get("pick_id") == pid:
            return rec
    return None
