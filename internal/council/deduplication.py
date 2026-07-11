"""Collapse near-duplicate pending predictions (Phase J2)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple


DEDUPE_WINDOW_SECONDS = 5 * 60


def _parse_dt(raw: Any) -> datetime:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def _dedupe_key(pred: Dict[str, Any]) -> Tuple[Any, float, int]:
    """Bucket created_at to 5-minute window for dedupe."""
    created = _parse_dt(pred.get("created_at"))
    bucket = int(created.timestamp()) // DEDUPE_WINDOW_SECONDS
    netuid = pred.get("netuid")
    predicted_pct = round(float(pred.get("predicted_pct", 0) or 0), 4)
    return netuid, predicted_pct, bucket


def _mark_duplicate(pred: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(pred)
    row["outcome"] = "duplicate"
    row["status"] = "duplicate"
    row["correct"] = None
    return row


def dedupe_predictions(
    predictions: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Keep first prediction per (netuid, predicted_pct, 5min bucket).

    Returns ``(kept, duplicates)`` so callers can move duplicates to resolved.
    """
    seen: set[Tuple[Any, float, int]] = set()
    kept: List[Dict[str, Any]] = []
    duplicates: List[Dict[str, Any]] = []
    for pred in predictions:
        if not isinstance(pred, dict):
            continue
        key = _dedupe_key(pred)
        if key in seen:
            duplicates.append(_mark_duplicate(pred))
            continue
        seen.add(key)
        kept.append(pred)
    return kept, duplicates


def mark_duplicates_in_resolved(resolved: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """When rebuilding stats, tag duplicate rows without deleting history."""
    seen: set[Tuple[Any, float, int]] = set()
    out: List[Dict[str, Any]] = []
    for pred in resolved:
        if not isinstance(pred, dict):
            continue
        key = _dedupe_key(pred)
        row = dict(pred)
        if key in seen:
            row = _mark_duplicate(row)
        else:
            seen.add(key)
        out.append(row)
    return out
