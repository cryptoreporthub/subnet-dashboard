"""Agent B — cockpit render helpers and cold-redeploy fallback (templates/server)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

_FALLBACK_IDS: tuple[str, ...] = (
    "council_picks",
    "judges",
    "learning_loop",
    "predictions",
    "scenario_memory",
    "pump_ladder",
    "pump_tracker",
    "trace",
    "message_intel",
    "mindmap_trail",
    "rotation",
    "soul_map",
)

_FALLBACK_TITLES: Dict[str, str] = {
    "council_picks": "Council Picks",
    "judges": "Judges",
    "learning_loop": "Learning Loop",
    "predictions": "Predictions",
    "scenario_memory": "Scenario Memory",
    "pump_ladder": "Pump Ladder",
    "pump_tracker": "Pump Tracker",
    "trace": "Decision Trace",
    "message_intel": "Message Intel",
    "mindmap_trail": "Mindmap Trail",
    "rotation": "Rotation Tokens",
    "soul_map": "Soul Map",
}


def _utcnow_z() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def empty_cockpit_sections(*, status: str = "empty") -> Dict[str, Any]:
    """Honest-empty payload — always exactly 12 sections for cold redeploy."""
    now = _utcnow_z()
    sections: List[Dict[str, Any]] = []
    for section_id in _FALLBACK_IDS:
        title = _FALLBACK_TITLES[section_id]
        sections.append(
            {
                "id": section_id,
                "title": title,
                "summary": (
                    f"{title} has no live data on this deploy yet. "
                    "Schedulers and stores will populate this card automatically."
                ),
                "metrics": {},
                "status": status,
                "updated_at": now,
            }
        )
    return {"status": "success", "sections": sections}


def load_cockpit_sections() -> Dict[str, Any]:
    """Prefer Agent A engine; never raise."""
    try:
        from internal.cockpit import get_cockpit_sections

        payload = get_cockpit_sections()
        sections = payload.get("sections") or []
        if len(sections) == 12:
            return payload
    except Exception:
        pass
    return empty_cockpit_sections()
