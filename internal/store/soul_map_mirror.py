"""Idempotent backfill from JSON trace file + read-only Soul-Map mirror."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

from internal.store.db import connect, create_tables
from internal.store.query import (
    _utcnow_z,
    upsert_decision_lineage_row,
    upsert_disposition,
    upsert_trail_row,
)

logger = logging.getLogger(__name__)

TRACE_STORE_PATH = os.environ.get("TRACE_STORE_PATH", "data/decision_trace.json")


def _load_json_trace(path: str) -> List[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        records = data.get("records") if isinstance(data, dict) else None
        if isinstance(records, list):
            return [row for row in records if isinstance(row, dict)]
    except Exception as exc:
        logger.debug("trace JSON backfill skipped for %s: %s", path, exc)
    return []


def _iter_disposition_maps(sms: Dict[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    """Yield (source, disposition_dict) pairs from Soul-Map state."""
    if not isinstance(sms, dict):
        return
    selector = sms.get("last_selector_output") or {}
    decisions = selector.get("decisions") or []
    if isinstance(decisions, list):
        for row in decisions:
            if isinstance(row, dict) and row.get("netuid") is not None:
                yield ("selector", row)

    for key in (
        "pump_dispositions",
        "message_intel_dispositions",
        "dispositions",
    ):
        block = sms.get(key)
        if isinstance(block, dict):
            for netuid_key, payload in block.items():
                if isinstance(payload, dict):
                    try:
                        netuid = int(netuid_key)
                    except (TypeError, ValueError):
                        netuid = payload.get("netuid")
                    if netuid is not None:
                        merged = dict(payload)
                        merged.setdefault("netuid", netuid)
                        yield (key, merged)


def _mirror_soul_map_dispositions(
    sms: Dict[str, Any],
    *,
    db_path: Optional[str] = None,
) -> int:
    count = 0
    updated_at = str(sms.get("updated_at") or _utcnow_z())
    for _source, row in _iter_disposition_maps(sms):
        netuid = row.get("netuid")
        if netuid is None:
            continue
        action = (
            row.get("recommended_action")
            or row.get("action")
            or row.get("disposition")
            or "hold"
        )
        score = row.get("score")
        if score is None:
            score = row.get("composite_score") or row.get("confidence")
        try:
            score_val = float(score) if score is not None else None
        except (TypeError, ValueError):
            score_val = None
        upsert_disposition(
            int(netuid),
            str(action),
            score_val,
            str(row.get("updated_at") or updated_at),
            db_path=db_path,
        )
        count += 1
    return count


def _mirror_soul_map_lineage(
    sms: Dict[str, Any],
    *,
    db_path: Optional[str] = None,
) -> int:
    lineage = sms.get("decision_lineage")
    if not isinstance(lineage, dict):
        return 0
    created_at = str(lineage.get("updated_at") or sms.get("updated_at") or _utcnow_z())
    row_id = f"lineage_{created_at.replace(':', '').replace('-', '')}"
    upsert_decision_lineage_row(
        row_id,
        created_at,
        int(lineage.get("total_records") or 0),
        lineage.get("top_signal_types") or [],
        lineage.get("last_record") or {},
        db_path=db_path,
    )
    return 1


def backfill_from_trace_json(
    path: Optional[str] = None,
    *,
    db_path: Optional[str] = None,
) -> int:
    records = _load_json_trace(path or TRACE_STORE_PATH)
    for record in records:
        upsert_trail_row(record, db_path=db_path)
    return len(records)


def backfill_from_soul_map(*, db_path: Optional[str] = None) -> Dict[str, int]:
    """Read-only Soul-Map import via MindmapBridge — never writes SOUL_MAP_PATH."""
    try:
        from internal.council.mindmap_bridge import MindmapBridge
        from internal.council.weights import SOUL_MAP_PATH

        bridge = MindmapBridge(persistence_path=SOUL_MAP_PATH)
        sms = bridge.soul_map_state or {}
    except Exception as exc:
        logger.warning("Soul-Map mirror read failed: %s", exc)
        return {"dispositions": 0, "lineage": 0}

    dispositions = _mirror_soul_map_dispositions(sms, db_path=db_path)
    lineage = _mirror_soul_map_lineage(sms, db_path=db_path)
    return {"dispositions": dispositions, "lineage": lineage}


def init_store(*, db_path: Optional[str] = None) -> None:
    """Idempotent: create tables + backfill from JSON trace + read-only Soul-Map mirror."""
    conn = connect(db_path)
    try:
        create_tables(conn)
    finally:
        conn.close()

    backfill_from_trace_json(db_path=db_path)
    backfill_from_soul_map(db_path=db_path)
