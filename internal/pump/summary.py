"""Plain-language pump ladder summary from live persisted state."""

from __future__ import annotations

from typing import Any, Dict, List

from internal.pump.constants import PHASE_ORDER
from internal.pump.state import get_ladder_snapshot, load_state


def _sentences(parts: List[str]) -> Dict[str, Any]:
    text = " ".join(p.strip() for p in parts if p and p.strip())
    return {"text": text, "sentences": [p.strip() for p in parts if p and p.strip()]}


def summarize_pump() -> Dict[str, Any]:
    """Return 3–4 sentences: phase distribution + recent transitions from LIVE state."""
    snap = get_ladder_snapshot()
    meta = snap.get("meta") or {}
    subnets = snap.get("subnets") or []
    phase_counts = meta.get("phase_counts") or {}

    if not subnets and not phase_counts:
        data = load_state()
        for entry in (data.get("subnets") or {}).values():
            ph = str(entry.get("phase", "DORMANT"))
            phase_counts[ph] = phase_counts.get(ph, 0) + 1

    tracked = int(meta.get("tracked_subnets") or len(subnets) or sum(phase_counts.values()))
    parts: List[str] = []

    if tracked == 0:
        parts.append(
            "The pump ladder has not scanned subnets yet; the boot scheduler will classify "
            "dormant → stirring → accumulating → pumping → cooling from live volume, price, "
            "message-intel chatter, and scenario tags."
        )
        parts.append(
            "Phase transitions update Soul-Map pump dispositions and emit Mindmap trail events "
            "when subnets climb or cool off the ladder."
        )
        return _sentences(parts)

    distribution = ", ".join(
        f"{phase} {phase_counts.get(phase, 0)}" for phase in PHASE_ORDER if phase_counts.get(phase, 0)
    ) or "all DORMANT"
    parts.append(
        f"The pump ladder tracks {tracked} subnets across five phases; current distribution: {distribution}."
    )

    recent_tx = int(meta.get("last_transition_count") or 0)
    if recent_tx:
        parts.append(
            f"The latest scan recorded {recent_tx} phase transition(s) with hysteresis locking "
            "to avoid flapping between adjacent rungs."
        )
    else:
        parts.append(
            "No subnets changed phase on the last scan — scores are stable inside their current lock windows."
        )

    leaders = subnets[:3]
    if leaders:
        leader_bits = [
            f"{s.get('name') or ('SN' + str(s.get('netuid')))} ({s.get('phase')}, score {float(s.get('composite_score') or 0):.2f})"
            for s in leaders
        ]
        parts.append(f"Top ladder candidates: {'; '.join(leader_bits)}.")

    last_scan = meta.get("last_scan_at")
    if last_scan:
        parts.append(f"Last full scan completed at {last_scan}.")

    return _sentences(parts[:4])
