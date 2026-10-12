"""
Scientific-method postmortems for wrong picks.

Each wrong resolution triggers three structured questions:
1. What did we get wrong? (direction, magnitude, or timing)
2. Why did the evidence point the wrong way? (signal failure mode)
3. What rule should we add or adjust next time? (actionable correction)

Postmortems are stored per-judge under ``data/postmortems/{judge}.json``.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

POSTMORTEMS_DIR = os.path.join("data", "postmortems")

def _path(judge_name: str) -> str:
    """Resolve the on-disk path for a judge's postmortem file (registry + containment)."""
    name = judge_name.lower()
    from internal.judges import get_judge

    if get_judge(name) is None:
        raise ValueError("Unknown judge")

    path = os.path.join(POSTMORTEMS_DIR, f"{name}.json")
    base = os.path.realpath(POSTMORTEMS_DIR)
    resolved = os.path.realpath(path)
    if resolved != base and not resolved.startswith(base + os.sep):
        raise ValueError("path outside postmortems directory")
    return path

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def _load(judge_name: str) -> List[Dict[str, Any]]:
    path = _path(judge_name)
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []

def _write_tmp_json(tmp: str, entries: List[Dict[str, Any]]) -> None:
    """Write JSON to a fresh tmp file; refuse pre-existing symlinks (TOCTOU hardening)."""
    if os.path.lexists(tmp):
        if os.path.islink(tmp):
            raise OSError("refusing to write postmortem tmp through symlink")
        os.unlink(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(entries, f, indent=2)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _save(judge_name: str, entries: List[Dict[str, Any]]) -> None:
    os.makedirs(POSTMORTEMS_DIR, exist_ok=True)
    path = _path(judge_name)
    tmp = path + ".tmp"
    _write_tmp_json(tmp, entries)
    os.replace(tmp, path)

def _diagnosis(prediction: Dict[str, Any], actual_pct: Optional[float]) -> Dict[str, str]:
    """Generate the four scientific-method questions for a wrong pick."""
    direction = prediction.get("direction", "up")
    predicted_pct = float(prediction.get("predicted_pct", 0) or 0)
    actual_pct = float(actual_pct or 0)
    signal_source = prediction.get("signal_source") or prediction.get("expert") or "unknown"

    if direction == "up" and actual_pct < 0:
        q1 = "Direction was wrong: predicted up but price fell."
    elif direction == "down" and actual_pct > 0:
        q1 = "Direction was wrong: predicted down but price rose."
    elif abs(actual_pct) < abs(predicted_pct) * 0.3:
        q1 = "Magnitude was wrong: the move was much smaller than predicted."
    else:
        q1 = "Timing/continuation was wrong: direction signalled but did not sustain."

    source_lower = str(signal_source).lower()
    if "sell" in source_lower or "bear" in source_lower:
        q2 = "Dark Horse/sell-alert signal over-interpreted a local pullback as trend."
    elif "hot" in source_lower or "momentum" in source_lower:
        q2 = "Momentum/hype signal chased short-term energy and ignored exhaustion."
    elif "rsi" in source_lower or "macd" in source_lower or "technical" in source_lower:
        q2 = "Technical indicator gave a false positive in a range-bound regime."
    else:
        q2 = "Supporting evidence was incomplete or stale relative to actual price action."

    q3 = (
        "Require a confirming second signal before taking a "
        f"{direction} position when {signal_source} is the primary driver."
    )

    opposite_direction = "down" if direction == "up" else "up"
    if actual_pct > 0:
        q4 = (
            f"To predict the opposite outcome I would have needed to believe that "
            f"{signal_source} was already priced in and that buyers were exhausted, "
            f"favouring a {opposite_direction} move instead."
        )
    elif actual_pct < 0:
        q4 = (
            f"To predict the opposite outcome I would have needed to believe that "
            f"the dip was overdone, support was holding, and risk/reward favoured "
            f"a {opposite_direction} reversal instead."
        )
    else:
        q4 = (
            "To predict the opposite outcome I would have needed to believe that "
            "the signal lacked follow-through and that the market would remain "
            "range-bound rather than follow the predicted direction."
        )

    return {"what": q1, "why": q2, "rule": q3, "devil": q4}

def record(
    judge_name: str,
    prediction: Dict[str, Any],
    actual_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """Record a new postmortem for a wrong pick."""
    entries = _load(judge_name)
    diagnosis = _diagnosis(prediction, actual_pct)
    entry = {
        "judge": judge_name.lower(),
        "prediction_id": prediction.get("id"),
        "netuid": prediction.get("netuid"),
        "name": prediction.get("name"),
        "direction": prediction.get("direction"),
        "predicted_pct": float(prediction.get("predicted_pct", 0) or 0),
        "actual_pct": round(float(actual_pct or 0), 4),
        "signal_source": prediction.get("signal_source") or prediction.get("expert"),
        "questions": diagnosis,
        "created_at": _utcnow(),
    }
    entries.append(entry)
    _save(judge_name, entries)
    return entry

def list_for_judge(judge_name: str) -> List[Dict[str, Any]]:
    """Return all postmortems for a judge, newest first."""
    return list(reversed(_load(judge_name)))


def _list_for_judge_fail_empty(judge_name: str) -> List[Dict[str, Any]]:
    """Like list_for_judge but returns [] when path validation fails (aggregate reads)."""
    try:
        return list_for_judge(judge_name)
    except ValueError:
        return []


def all_postmortems() -> Dict[str, List[Dict[str, Any]]]:
    """Return postmortems for all three judges."""
    return {
        "oracle": _list_for_judge_fail_empty("oracle"),
        "echo": _list_for_judge_fail_empty("echo"),
        "pulse": _list_for_judge_fail_empty("pulse"),
    }
