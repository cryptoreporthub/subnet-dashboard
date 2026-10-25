"""Score-time pump desk prior — blends into council total, never soul_map weights."""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, Optional, Tuple

_EARLY_PHASES = frozenset({"STIRRING", "ACCUMULATING"})
_CONFIRMED_PHASES = frozenset({"PUMPING"})
# One parsed ladder per mtime. Pick loops call this once per subnet; re-parsing
# the whole file each time leaves the arena resident. A new mtime reloads.
_ladder_memo_lock = threading.Lock()
_ladder_memo: Dict[str, Any] = {"key": None, "data": None}


def overlay_alpha() -> float:
    raw = os.environ.get("PUMP_SCORE_OVERLAY_ALPHA", "0.10").strip()
    try:
        alpha = float(raw)
    except (TypeError, ValueError):
        alpha = 0.10
    return max(0.0, min(0.25, alpha))


def _readonly_ladder() -> Dict[str, Any]:
    """Return the on-disk ladder, parsing it once per mtime and size."""
    # Imported here: pump.state loads the signal fetcher, which imports this module.
    from internal.pump.state import _resolve_path, load_state

    path = _resolve_path(None)
    try:
        st = os.stat(path)
        key = (path, st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    with _ladder_memo_lock:
        if key is not None and _ladder_memo.get("key") == key and isinstance(_ladder_memo.get("data"), dict):
            return _ladder_memo["data"]
        data = load_state()
        if not isinstance(data, dict):
            data = {}
        if key is not None:
            _ladder_memo["key"] = key
            _ladder_memo["data"] = data
        return data


def pump_ladder_entry(
    netuid: int,
    pump_ladder_state: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    try:
        if pump_ladder_state is not None:
            st = pump_ladder_state
        else:
            st = _readonly_ladder()
        subnets = st.get("subnets") if isinstance(st, dict) else {}
        if not isinstance(subnets, dict):
            return None
        entry = subnets.get(str(netuid)) or subnets.get(netuid)
        return dict(entry) if isinstance(entry, dict) else None
    except Exception:
        return None


def pump_prior_0_1(entry: Dict[str, Any]) -> Optional[float]:
    """Map ladder phase + composite score → 0..1 bullish prior."""
    phase = str(entry.get("phase") or "DORMANT").upper()
    try:
        score = float(entry.get("composite_score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(1.0, score))
    if phase in _EARLY_PHASES:
        return round(0.42 + score * 0.35, 4)
    if phase in _CONFIRMED_PHASES:
        return round(0.38 + score * 0.28, 4)
    if phase == "COOLING":
        return round(0.28 + score * 0.12, 4)
    return None


def apply_pump_score_overlay(
    total_score: float,
    subnet_data: Dict[str, Any],
    *,
    pump_ladder_state: Optional[Dict[str, Any]] = None,
) -> Tuple[float, Optional[Dict[str, Any]]]:
    """Blend council total (0–100) with pump prior. No persistence."""
    alpha = overlay_alpha()
    if alpha <= 0:
        return total_score, None
    netuid = subnet_data.get("netuid") or subnet_data.get("id")
    if netuid is None:
        return total_score, None
    try:
        nu = int(netuid)
    except (TypeError, ValueError):
        return total_score, None
    entry = pump_ladder_entry(nu, pump_ladder_state=pump_ladder_state)
    if not entry:
        return total_score, None
    prior = pump_prior_0_1(entry)
    if prior is None:
        return total_score, None
    prior_pct = prior * 100.0
    blended = round((1.0 - alpha) * float(total_score) + alpha * prior_pct, 2)
    blended = min(100.0, max(0.0, blended))
    return blended, {
        "alpha": alpha,
        "prior": prior,
        "phase": str(entry.get("phase") or "").upper(),
        "composite_score": entry.get("composite_score"),
        "before": round(float(total_score), 2),
        "after": blended,
    }
