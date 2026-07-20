"""Council / expert hot streaks from graded predictions.

Appear at length ≥3; clear on the first miss. Calm authority — no XP/levels.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from internal.learning.predictions_store import load_predictions

STREAK_THRESHOLD = 3
_SKIP = frozenset({"duplicate", "expired", "ungradeable"})
_EXPERT_LABEL = {
    "quant": "Quant",
    "hype": "Hype",
    "dark_horse": "Dark Horse",
    "technical": "Technical",
}


def _resolved_hits(data: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    raw = data if isinstance(data, dict) else load_predictions()
    rows: List[Dict[str, Any]] = []
    for pred in raw.get("resolved") or []:
        if not isinstance(pred, dict):
            continue
        if pred.get("outcome") in _SKIP:
            continue
        if pred.get("correct") is not True and pred.get("correct") is not False:
            continue
        rows.append(pred)
    rows.sort(key=lambda p: str(p.get("resolved_at") or p.get("created_at") or ""))
    return rows


def _tail_streak(flags: List[bool]) -> int:
    """Count consecutive True at the end of the list."""
    n = 0
    for flag in reversed(flags):
        if flag is True:
            n += 1
        else:
            break
    return n


def _streak_payload(length: int, label: str) -> Dict[str, Any]:
    active = length >= STREAK_THRESHOLD
    return {
        "length": length,
        "active": active,
        "label": f"{label} · {length} in a row" if active else None,
    }


def compute_streaks(data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return council + per-expert streak snapshots."""
    rows = _resolved_hits(data)
    council_flags = [bool(r.get("correct")) for r in rows]
    council = _streak_payload(_tail_streak(council_flags), "Council")

    experts: Dict[str, Dict[str, Any]] = {}
    for key, label in _EXPERT_LABEL.items():
        aliases = {key}
        if key == "dark_horse":
            aliases.add("contrarian")
        flags = [
            bool(r.get("correct"))
            for r in rows
            if str(r.get("expert") or "").lower().strip() in aliases
        ]
        experts[key] = _streak_payload(_tail_streak(flags), label)

    whisper_parts: List[str] = []
    if council.get("label"):
        whisper_parts.append(council["label"])
    # At most one expert streak in the whisper (hottest)
    hot_expert = None
    hot_len = 0
    for key, payload in experts.items():
        if payload.get("active") and int(payload.get("length") or 0) > hot_len:
            hot_len = int(payload["length"])
            hot_expert = payload.get("label")
    if hot_expert and hot_expert not in whisper_parts:
        whisper_parts.append(hot_expert)

    return {
        "council": council,
        "experts": experts,
        "whisper": " · ".join(whisper_parts) if whisper_parts else None,
        "threshold": STREAK_THRESHOLD,
    }
