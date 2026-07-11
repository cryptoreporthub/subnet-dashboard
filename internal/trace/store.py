"""Decision lineage (trace) store for Phase C."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

TRACE_STORE_PATH = os.environ.get("TRACE_STORE_PATH", "data/decision_trace.json")
MAX_RECORDS = 500


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _empty_store() -> Dict[str, Any]:
    return {"meta": {"version": 1, "last_updated": None}, "records": []}


def load_store(path: Optional[str] = None) -> Dict[str, Any]:
    path = path or TRACE_STORE_PATH
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


def save_store(data: Dict[str, Any], path: Optional[str] = None) -> None:
    path = path or TRACE_STORE_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    data.setdefault("meta", {})
    data["meta"]["last_updated"] = _utcnow_z()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)


def list_records(limit: int = 100, path: Optional[str] = None) -> List[Dict[str, Any]]:
    records = load_store(path=path).get("records") or []
    if not isinstance(records, list):
        return []
    return list(reversed(records[-limit:]))


def get_record(trace_id: str, path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    for row in load_store(path=path).get("records") or []:
        if isinstance(row, dict) and row.get("id") == trace_id:
            return row
    return None


def append_record(record: Dict[str, Any], path: Optional[str] = None) -> Dict[str, Any]:
    data = load_store(path=path)
    records = data.setdefault("records", [])
    if not isinstance(records, list):
        records = []
        data["records"] = records
    records.append(record)
    if len(records) > MAX_RECORDS:
        data["records"] = records[-MAX_RECORDS:]
    save_store(data, path=path)
    return record
