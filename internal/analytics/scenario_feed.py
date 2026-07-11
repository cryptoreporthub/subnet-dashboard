"""Scenario trail subscriber — detects new scenario snapshots without council edits."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Set

from internal.analytics.scenario_state import load_scenario_snapshot
from internal.analytics.trail_cursor import mark_scenarios_seen, seen_scenario_ids

logger = logging.getLogger(__name__)


def _emit_scenario_tagged(scenario: Dict[str, Any]) -> None:
    """Emit scenario_tagged via existing trail bus (call-only)."""
    try:
        from internal.learning.trail_events import emit_trail_event
    except Exception as exc:
        logger.warning("Could not import trail emitter: %s", exc)
        return

    features = scenario.get("features") or {}
    emit_trail_event(
        "scenario_tagged",
        subnet=scenario.get("name"),
        evidence={
            "scenario_id": scenario.get("id"),
            "regime": scenario.get("regime"),
            "features": features,
            "outcome": scenario.get("outcome"),
            "tags": _extract_tags(features),
        },
        signal=scenario.get("regime"),
        decision="scenario_snapshot_recorded",
    )


def _extract_tags(features: Dict[str, Any]) -> List[str]:
    tags: List[str] = []
    for key in ("direction", "expert", "rsi", "volume", "outcome"):
        val = features.get(key)
        if val:
            tags.append(f"{key}:{val}")
    extra = features.get("tags")
    if isinstance(extra, list):
        tags.extend(str(t) for t in extra)
    elif isinstance(extra, dict):
        tags.extend(f"{k}:{v}" for k, v in extra.items())
    return tags


def sync_scenario_trail_events(
    snapshot: Dict[str, Any] | None = None,
    *,
    path: str | None = None,
) -> int:
    """Poll scenario memory and emit trail rows for newly seen scenario IDs.

    Reads ``data/scenario_memory.json`` (same source as GET /api/scenario-memory)
    without importing ``internal.council``. Returns count of events emitted.
    """
    state = snapshot if snapshot is not None else load_scenario_snapshot(path=path)
    scenarios = state.get("scenarios") or []
    known: Set[str] = seen_scenario_ids()

    # First poll after deploy: seed cursor without replaying entire history.
    if not known and scenarios:
        bootstrap_scenario_cursor(state)
        return 0

    emitted = 0
    new_ids: Set[str] = set()

    for scenario in scenarios:
        sid = scenario.get("id")
        if not sid or sid in known:
            continue
        _emit_scenario_tagged(scenario)
        new_ids.add(str(sid))
        emitted += 1

    if new_ids:
        mark_scenarios_seen(new_ids)
    return emitted


def bootstrap_scenario_cursor(snapshot: Dict[str, Any] | None = None) -> None:
    """Mark all existing scenarios seen without emitting (for first deploy)."""
    state = snapshot if snapshot is not None else load_scenario_snapshot()
    ids = {str(s.get("id")) for s in state.get("scenarios") or [] if s.get("id")}
    if ids:
        mark_scenarios_seen(ids)
