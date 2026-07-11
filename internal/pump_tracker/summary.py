"""Plain-language summary for the pump-tracker ladder panel (Phase D)."""

from __future__ import annotations

from typing import Any, Dict, List

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
            "When Agent A's internal.pump detection lands, this panel will read phases "
            "from that engine automatically via guarded imports."
        )
        return _sentences(parts)

    total = int(stats.get("total_subnets") or 0)
    phase_counts: Dict[str, int] = stats.get("phase_counts") or {}
    source = stats.get("source", "unknown")
    meta = stats.get("meta") or {}

    if total == 0:
        parts.append(
            "Pump-tracker ladder has no subnet rows yet — price/volume ticks have not "
            "seeded phase state across the registry."
        )
    else:
        distribution = ", ".join(
            f"{phase} {count}" for phase, count in sorted(phase_counts.items(), key=lambda kv: -kv[1])
        )
        parts.append(
            f"The pump ladder tracks {total} subnets from {source}; "
            f"phase distribution is {distribution or 'all INACTIVE'}."
        )

        early = phase_counts.get("EARLY", 0)
        sell = phase_counts.get("SELL", 0)
        if early or sell:
            parts.append(
                f"{early} subnet(s) sit in EARLY accumulation and {sell} in SELL distribution — "
                "these are the highest-signal ladder rungs for Pulse and trail consumers."
            )
        else:
            parts.append(
                "No subnets are in EARLY or SELL right now; most names are consolidating or inactive."
            )

    movers = stats.get("top_movers") or []
    if movers:
        top = movers[0]
        parts.append(
            f"Largest recent transition: SN{top.get('netuid')} moved "
            f"{top.get('from_phase')} → {top.get('to_phase')} "
            f"(max score {float(top.get('max_score') or 0):.2f})."
        )
    else:
        parts.append(
            f"Cycle store reports {meta.get('total_cycles', 0)} transitions; "
            "no fresh phase movers in the latest window."
        )

    return _sentences(parts[:4])
