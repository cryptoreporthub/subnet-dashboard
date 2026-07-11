"""Agent B — cockpit render helpers and cold-redeploy fallback (templates/server)."""

from __future__ import annotations

import re
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


def _strip_markdown_headings(text: str) -> str:
    """Remove markdown heading markers from summaries (H-thin: zero ### in HTML)."""
    if not text:
        return text
    cleaned = text.replace("###", "")
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
    return cleaned.strip()


def _enrich_judges_metrics(section: Dict[str, Any]) -> None:
    """Add real judge P&L metrics for template highlights (read-only)."""
    try:
        from internal.judges.portfolios import _load as load_portfolios
    except Exception:
        return

    data = load_portfolios()
    metrics = dict(section.get("metrics") or {})
    combined_pnl = 0.0
    combined_open = 0
    for name in ("oracle", "echo", "pulse"):
        block = data.get(name) or {}
        summary = block.get("summary") or {}
        win_pct = float(summary.get("win_pct", 0) or 0)
        pnl_pct = float(summary.get("total_pnl_pct", 0) or 0)
        open_n = int(summary.get("open_positions", 0) or 0)
        metrics[f"{name}_win_pct"] = round(win_pct, 1)
        metrics[f"{name}_pnl_pct"] = round(pnl_pct, 2)
        metrics[f"{name}_open"] = open_n
        combined_pnl += pnl_pct
        combined_open += open_n
    metrics["combined_pnl_pct"] = round(combined_pnl, 2)
    metrics["combined_open"] = combined_open
    section["metrics"] = metrics


def enrich_cockpit_sections_for_display(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize summaries and attach H-thin highlight metrics without touching Agent A data layer."""
    sections = payload.get("sections") or []
    for section in sections:
        if not isinstance(section, dict):
            continue
        summary = section.get("summary")
        if isinstance(summary, str):
            section["summary"] = _strip_markdown_headings(summary)

        section_id = section.get("id")
        metrics = section.get("metrics") or {}

        if section_id == "learning_loop" and metrics:
            accuracy = metrics.get("accuracy")
            if accuracy is not None:
                section["highlights"] = {
                    "accuracy_pct": round(float(accuracy) * 100, 1),
                    "correct": int(metrics.get("correct", 0) or 0),
                    "wrong": int(metrics.get("wrong", 0) or 0),
                    "pending": int(metrics.get("pending", 0) or 0),
                }

        if section_id == "judges" and section.get("status") == "live":
            _enrich_judges_metrics(section)
            metrics = section.get("metrics") or {}
            if metrics.get("combined_pnl_pct") is not None:
                section["highlights"] = {
                    "combined_pnl_pct": metrics["combined_pnl_pct"],
                    "combined_open": metrics.get("combined_open", 0),
                    "oracle_pnl_pct": metrics.get("oracle_pnl_pct"),
                    "echo_pnl_pct": metrics.get("echo_pnl_pct"),
                    "pulse_pnl_pct": metrics.get("pulse_pnl_pct"),
                }

    return payload


def load_cockpit_sections() -> Dict[str, Any]:
    """Prefer Agent A engine; never raise."""
    try:
        from internal.cockpit import get_cockpit_sections

        payload = get_cockpit_sections()
        sections = payload.get("sections") or []
        if len(sections) == 12:
            return enrich_cockpit_sections_for_display(payload)
    except Exception:
        pass
    return enrich_cockpit_sections_for_display(empty_cockpit_sections())
