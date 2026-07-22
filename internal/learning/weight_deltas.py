"""Recent council expert weight nudges for hero UI."""

from __future__ import annotations

from typing import Any, Dict

_CANONICAL = frozenset({"quant", "hype", "dark_horse", "technical"})


def _normalize_expert(raw: Any) -> str | None:
    name = str(raw or "").lower().strip().replace(" ", "_")
    if name == "darkhorse":
        name = "dark_horse"
    return name if name in _CANONICAL else None


def recent_expert_weight_deltas(limit: int = 80) -> Dict[str, float]:
    """Latest nudge delta per expert from mindmap weight_change trail rows."""
    try:
        from internal.learning.mindmap_aggregator import collect_trail_events
        from internal.learning.trail_bus import normalize_event_type
    except Exception:
        return {}

    out: Dict[str, float] = {}
    for row in collect_trail_events(limit):
        if not isinstance(row, dict):
            continue
        if normalize_event_type(row.get("event_type")) != "weight_change":
            continue
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        expert = _normalize_expert(row.get("judge") or evidence.get("dial"))
        if not expert or expert in out:
            continue
        try:
            out[expert] = round(float(evidence.get("delta")), 4)
        except (TypeError, ValueError):
            continue
    return out
