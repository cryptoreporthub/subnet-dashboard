"""Plain-language summary for the decision lineage (trace) panel."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from internal.trace.store import list_records, load_store


def summarize_trace(
    store: Optional[Dict[str, Any]] = None,
    *,
    limit: int = 100,
) -> str:
    """Return 3–4 sentences from live trace store state."""
    data = store if store is not None else load_store()
    records: List[Dict[str, Any]] = data.get("records") or []
    recent = list_records(limit=limit) if store is None else list(reversed(records[-limit:]))

    if not records:
        return (
            "Decision lineage is empty — no signal→decision chains have been recorded yet. "
            "When pump phases, scenario tags, Soul-Map dispositions, or judge signals "
            "feed a council pick or weight change, a trace row will appear here. "
            "Each record also mirrors into Soul-Map and emits a Mindmap trail event."
        )

    total = len(records)
    decision_types: Counter[str] = Counter()
    signal_types: Counter[str] = Counter()
    for row in records:
        decision_types[str(row.get("decision_type", "unknown"))] += 1
        for sig in row.get("signals") or []:
            signal_types[str(sig.get("type", "unknown"))] += 1

    top_decisions = ", ".join(f"{k} ({v})" for k, v in decision_types.most_common(3))
    top_signals = ", ".join(f"{k} ({v})" for k, v in signal_types.most_common(4)) or "none yet"

    latest = recent[0] if recent else records[-1]
    latest_subnet = latest.get("subnet") or f"SN{latest.get('netuid')}" or "unknown"
    latest_type = latest.get("decision_type", "decision")
    signal_count = len(latest.get("signals") or [])

    meta = data.get("meta") or {}
    updated = meta.get("last_updated", "recently")

    return (
        f"The lineage store holds {total} traced decisions; most common types are {top_decisions}. "
        f"Top contributing signal types: {top_signals}. "
        f"The latest trace links {signal_count} signal(s) to a {latest_type} on {latest_subnet}. "
        f"Store last updated {updated}."
    )
