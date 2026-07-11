"""Durable SQLite store — trace rows, dispositions, decision lineage (Phase F)."""

from __future__ import annotations

import logging

from internal.store.query import (
    count_decision_lineage,
    count_dispositions,
    count_trail,
    get_decision_lineage,
    get_dispositions,
    get_store_stats,
    get_trail_rows,
    record_trace_row,
)
from internal.store.soul_map_mirror import init_store

logger = logging.getLogger(__name__)

__all__ = [
    "init_store",
    "record_trace_row",
    "get_trail_rows",
    "get_dispositions",
    "get_decision_lineage",
    "count_trail",
    "count_dispositions",
    "count_decision_lineage",
    "get_store_stats",
    "sqlite_available",
]

_sqlite_ready = False


def _bootstrap() -> None:
    global _sqlite_ready
    try:
        init_store()
        _sqlite_ready = True
    except Exception as exc:
        _sqlite_ready = False
        logger.warning("SQLite store init failed — JSON trace fallback only: %s", exc)


def sqlite_available() -> bool:
    return _sqlite_ready


_bootstrap()
