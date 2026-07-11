"""Decision lineage (trace) store — SQLite primary with JSON fallback (Phase F)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TRACE_STORE_PATH = os.environ.get("TRACE_STORE_PATH", "data/decision_trace.json")
MAX_RECORDS = 500
# Captured at import — tests that monkeypatch TRACE_STORE_PATH stay JSON-only.
_CANONICAL_TRACE_PATH = TRACE_STORE_PATH


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _empty_store() -> Dict[str, Any]:
    return {"meta": {"version": 1, "last_updated": None}, "records": []}


def _resolve_path(path: Optional[str]) -> str:
    return path or TRACE_STORE_PATH


def _sqlite_enabled(path: Optional[str]) -> bool:
    """SQLite backs only the canonical trace path (isolated tmp paths stay JSON-only)."""
    if _resolve_path(path) != _CANONICAL_TRACE_PATH:
        return False
    try:
        from internal.store import sqlite_available

        return bool(sqlite_available())
    except Exception:
        return False


def _load_json_store(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            data.setdefault("records", [])
            data.setdefault("meta", {})
            return data
    except Exception:
        pass
    return _empty_store()


def load_store(path: Optional[str] = None) -> Dict[str, Any]:
    store_path = _resolve_path(path)
    if _sqlite_enabled(path):
        try:
            from internal.store import get_trail_rows

            rows = get_trail_rows(limit=MAX_RECORDS)
            chronological = list(reversed(rows))
            return {
                "meta": {
                    "version": 1,
                    "last_updated": _utcnow_z(),
                    "backend": "sqlite",
                },
                "records": chronological,
            }
        except Exception as exc:
            logger.warning("SQLite load_store fallback to JSON: %s", exc)

    return _load_json_store(store_path)


def save_store(data: Dict[str, Any], path: Optional[str] = None) -> None:
    """Compat: persist JSON fallback; SQLite rows are written via append_record."""
    store_path = _resolve_path(path)
    os.makedirs(os.path.dirname(store_path) or ".", exist_ok=True)
    data.setdefault("meta", {})
    data["meta"]["last_updated"] = _utcnow_z()
    tmp = store_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, store_path)


def list_records(limit: int = 100, path: Optional[str] = None) -> List[Dict[str, Any]]:
    if _sqlite_enabled(path):
        try:
            from internal.store import get_trail_rows

            return get_trail_rows(limit=limit)
        except Exception as exc:
            logger.warning("SQLite list_records fallback to JSON: %s", exc)

    records = _load_json_store(_resolve_path(path)).get("records") or []
    if not isinstance(records, list):
        return []
    return list(reversed(records[-limit:]))


def get_record(trace_id: str, path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if _sqlite_enabled(path):
        try:
            from internal.store.query import get_trail_row

            return get_trail_row(trace_id)
        except Exception as exc:
            logger.warning("SQLite get_record fallback to JSON: %s", exc)

    for row in _load_json_store(_resolve_path(path)).get("records") or []:
        if isinstance(row, dict) and row.get("id") == trace_id:
            return row
    return None


def append_record(record: Dict[str, Any], path: Optional[str] = None) -> Dict[str, Any]:
    store_path = _resolve_path(path)
    data = _load_json_store(store_path)
    records = data.setdefault("records", [])
    if not isinstance(records, list):
        records = []
        data["records"] = records
    records.append(record)
    if len(records) > MAX_RECORDS:
        data["records"] = records[-MAX_RECORDS:]
    save_store(data, path=store_path)

    if _sqlite_enabled(path):
        try:
            from internal.store import record_trace_row

            record_trace_row(record)
        except Exception as exc:
            logger.warning("SQLite record_trace_row failed (JSON persisted): %s", exc)

    return record
