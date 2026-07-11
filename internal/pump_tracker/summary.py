"""Plain-language summary for the pump-tracker ladder panel (Phase D)."""

from __future__ import annotations

from typing import Any, Dict, List

from internal.pump.constants import PHASE_ORDER
from internal.pump_tracker.adapter import live_stats


def _sentences(parts: List[str]) -> Dict[str, Any]:
    text = " ".join(p.strip() for p in parts if p and p.strip())
    return {"text": text, "sentences": [p.strip() for p in parts if p and p.strip()]}


def summarize_pump_tracker() -> Dict[str, Any]:
    """Return 3–4 sentences from live pump-tracker ladder state."""
    stats = live_stats()
    parts: List[str] = []

    if not stats.get("ok"):
        parts.append(
            f"Pump tracker engine is unavailable ({stats.get('error', 'unknown')}); "
            "ladder endpoints return a clear degraded response instead of a 500."
        )
        parts.append(
            "The panel reads Agent A's internal.pump ladder when present and otherwise "
            "returns an honest empty state."
        )
        return _sentences(parts)

    total = int(stats.get("total_subnets") or 0)
    phase_counts: Dict[str, int] = stats.get("phase_counts") or {}
    source = stats.get("source", "unknown")
    meta = stats.get("meta") or {}

    if total == 0:
        parts.append(
            "Pump-tracker ladder has no subnet rows yet — the detection engine has not "
            "seeded phase state across the registry."
        )
    else:
        order_index = {p: i for i, p in enumerate(PHASE_ORDER)}
        distribution = ", ".join(
            f"{phase} {count}"
            for phase, count in sorted(
                phase_counts.items(),
                key=lambda kv: order_index.get(kv[0], 99),
            )
        )
        parts.append(
            f"The pump ladder tracks {total} subnets from {source}; "
            f"phase distribution is {distribution or 'all DORMANT'}."
        )

        accumulating = phase_counts.get("ACCUMULATING", 0)
        pumping = phase_counts.get("PUMPING", 0)
        stirring = phase_counts.get("STIRRING", 0)
        signal_count = accumulating + pumping + stirring
        if signal_count:
            parts.append(
                f"{stirring} subnet(s) are STIRRING, {accumulating} ACCUMULATING, and "
                f"{pumping} PUMPING — the highest-signal ladder rungs for Pulse and trail consumers."
            )
        else:
            parts.append(
                "No subnets are in STIRRING, ACCUMULATING, or PUMPING right now; "
                "most names are DORMANT or COOLING."
            )

    movers = stats.get("top_movers") or []
    if movers:
        top = movers[0]
        score = float(top.get("composite_score") or top.get("max_score") or 0.0)
        parts.append(
            f"Largest recent transition: SN{top.get('netuid')} moved "
            f"{top.get('from_phase')} → {top.get('to_phase')} "
            f"(score {score:.2f})."
        )
    else:
        parts.append(
            f"Ladder meta reports {meta.get('last_transition_count', meta.get('total_cycles', 0))} "
            "recent transitions; no fresh movers in the latest window."
        )

    return _sentences(parts[:4])
