"""Plain-language summary for the Pump Tracker panel (Phase B)."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional


_SIGNAL_PHASES = {"EARLY", "SELL", "SECOND_WIND"}


def summarize_pump(pump_state: Optional[Dict[str, Any]] = None) -> str:
    """Return 3–4 sentences from live pump analytics payload.

    Accepts the dict from ``PumpTracker.get_all_analytics()`` or
    ``GET /api/pump-analytics`` (``status``, ``data.subnets``, ``data.meta``).
    """
    state = pump_state or {}
    data = state.get("data") or {}
    subnets: List[Dict[str, Any]] = data.get("subnets") or []
    meta = data.get("meta") or {}

    if not subnets:
        return (
            "Pump tracker has no active subnet cycles in state yet. "
            "As price/volume snapshots arrive, subnets move through the "
            "five-phase ladder (INACTIVE → EARLY → EXHAUSTING → CONSOLIDATING → "
            "SECOND_WIND → SELL). EARLY and SELL transitions will emit trail "
            "signals when the ladder advances."
        )

    phase_counts: Counter[str] = Counter()
    for row in subnets:
        phase_counts[str(row.get("current_phase", "INACTIVE"))] += 1

    tracked = int(meta.get("tracked_subnets") or len(subnets))
    total_cycles = int(meta.get("total_cycles") or 0)
    avg_proneness = float(meta.get("avg_proneness") or 0.0)

    distribution = ", ".join(
        f"{phase} {count}" for phase, count in phase_counts.most_common()
    )

    signals: List[str] = []
    for row in subnets:
        phase = str(row.get("current_phase", "INACTIVE"))
        if phase not in _SIGNAL_PHASES:
            continue
        name = row.get("name") or f"SN{row.get('netuid')}"
        proneness = row.get("pump_proneness", 0)
        signals.append(f"{name} in {phase} (proneness {proneness})")

    if signals:
        signal_text = (
            f" Notable ladder signals: {'; '.join(signals[:5])}"
            + ("." if len(signals) <= 5 else f" (+{len(signals) - 5} more).")
        )
    else:
        signal_text = " No subnets are currently in EARLY or SELL phases."

    top = subnets[0]
    leader = top.get("name") or f"SN{top.get('netuid')}"
    leader_phase = top.get("current_phase", "INACTIVE")
    leader_score = top.get("final_score", 0.0)

    return (
        f"Pump tracker is watching {tracked} subnets across {total_cycles} recorded "
        f"cycle transitions; average proneness is {avg_proneness:.1f}. "
        f"Phase distribution: {distribution}. "
        f"The top candidate is {leader} in {leader_phase} "
        f"(final score {float(leader_score):.2f}).{signal_text}"
    )
