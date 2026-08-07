"""Recent council expert weight nudges for hero UI."""

from __future__ import annotations

from typing import Any, Dict

_CANONICAL = frozenset({"quant", "hype", "dark_horse", "technical"})
_JUDGES = frozenset({"oracle", "echo", "pulse"})


def _normalize_expert(raw: Any) -> str | None:
    name = str(raw or "").lower().strip().replace(" ", "_")
    if name == "darkhorse":
        name = "dark_horse"
    return name if name in _CANONICAL else None


_SKIP_GRADED_OUTCOMES = frozenset({"duplicate", "expired", "ungradeable"})


def expert_graded_counts() -> Dict[str, int]:
    """Resolved prediction count per canonical expert (for honest Bench badges)."""
    counts = {name: 0 for name in _CANONICAL}
    try:
        from internal.learning.predictions_store import load_predictions

        for pred in load_predictions().get("resolved") or []:
            if not isinstance(pred, dict):
                continue
            if pred.get("outcome") in _SKIP_GRADED_OUTCOMES:
                continue
            if pred.get("correct") is None:
                continue
            expert = _normalize_expert(pred.get("expert"))
            if expert:
                counts[expert] = counts.get(expert, 0) + 1
    except Exception:
        pass
    return counts


# collect_trail_events returns oldest-first and truncates at limit, so a small
# window silently drops the newest weight_change rows. Scan a window wider than
# the persisted trail (capped at 200 rows) and walk it newest-first so the
# first delta seen per dial really is the latest.
_TRAIL_SCAN_LIMIT = 500


def collect_weight_trail_events(limit: int = _TRAIL_SCAN_LIMIT) -> list:
    """Trail rows for delta scans — collect once, reuse for expert + judge dials.

    ``collect_trail_events`` re-reads the soul map, the prediction ledger and the
    dev-signal trail on every call (seconds on a warm prod volume). Callers that
    need both dial families should collect once and pass the result in.
    """
    try:
        from internal.learning.mindmap_aggregator import collect_trail_events
    except Exception:
        return []
    try:
        return collect_trail_events(limit)
    except Exception:
        return []


def recent_expert_weight_deltas(
    limit: int = _TRAIL_SCAN_LIMIT,
    events: Any = None,
) -> Dict[str, float]:
    """Latest nudge delta per expert from mindmap weight_change trail rows."""
    try:
        from internal.learning.trail_bus import normalize_event_type
    except Exception:
        return {}

    rows = events if isinstance(events, list) else collect_weight_trail_events(limit)
    out: Dict[str, float] = {}
    for row in reversed(rows):
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


def _normalize_judge(raw: Any) -> str | None:
    name = str(raw or "").lower().strip()
    return name if name in _JUDGES else None


def recent_judge_weight_deltas(
    limit: int = _TRAIL_SCAN_LIMIT,
    events: Any = None,
) -> Dict[str, float]:
    """Latest nudge delta per judge (oracle/echo/pulse) from weight_change trail."""
    try:
        from internal.learning.trail_bus import normalize_event_type
    except Exception:
        return {}

    rows = events if isinstance(events, list) else collect_weight_trail_events(limit)
    out: Dict[str, float] = {}
    for row in reversed(rows):
        if not isinstance(row, dict):
            continue
        if normalize_event_type(row.get("event_type")) != "weight_change":
            continue
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        judge = _normalize_judge(row.get("judge") or evidence.get("dial"))
        if not judge or judge in out:
            continue
        try:
            out[judge] = round(float(evidence.get("delta")), 4)
        except (TypeError, ValueError):
            continue
    return out
