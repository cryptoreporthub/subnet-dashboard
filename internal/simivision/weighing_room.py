"""Conviction Board — Weighing Room presentation fields.

Shapes simivision ``top`` rows into deliberation cards: proximity sort,
NEAR-CALL / WEIGHING / FADING states, Daily Call exclusion, and v1.1 meta
(gap tick, quiet-table count, handoff clock).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

NEAR_CALL_MIN_PROXIMITY = 82
FADING_MAX_PROXIMITY = 48
MAX_ROWS = 5
CANDIDATE_POOL = 12


def conviction_pct(raw: Any) -> int:
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return 0
    if 0.0 <= val <= 1.0:
        val *= 100.0
    return max(0, min(100, int(round(val))))


def proximity_to_call(pick_conv: int, call_conv: Optional[int]) -> int:
    """0–100 closeness to today's call conviction (100 = same bar)."""
    if call_conv is None:
        return max(0, min(100, int(pick_conv)))
    return max(0, min(100, 100 - abs(int(pick_conv) - int(call_conv))))


def deliberation_state(proximity: int, delta: int) -> str:
    if proximity >= NEAR_CALL_MIN_PROXIMITY and delta >= -1:
        return "NEAR-CALL"
    if delta <= -3 or proximity < FADING_MAX_PROXIMITY:
        return "FADING"
    return "WEIGHING"


def _human_updated_ago(updated_at: Optional[str]) -> str:
    if not updated_at:
        return "updated just now"
    try:
        ts = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
    except ValueError:
        return "updated recently"
    age = int((datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds())
    if age < 60:
        return "updated just now"
    if age < 3600:
        return f"updated {age // 60}m ago"
    if age < 86400:
        return f"updated {age // 3600}h ago"
    return f"updated {age // 86400}d ago"


def _near_call_strip(reason: str, *, resolves_in: Optional[str] = None) -> str:
    base = (reason or "conviction holds near the bar").strip()
    if len(base) > 70:
        base = base[:67].rstrip() + "…"
    lead = base[:1].lower() + base[1:] if base else "conviction holds near the bar"
    if resolves_in:
        return f"Near the call bar while {lead} · {resolves_in} to lock"
    return f"Near the call bar while {lead}"


def _delta_for(netuid: Any, conviction: int, last: Dict[str, Any]) -> int:
    key = str(netuid) if netuid is not None else ""
    prev = last.get(key)
    if prev is None:
        return 0
    try:
        return int(round(float(conviction) - float(prev)))
    except (TypeError, ValueError):
        return 0


def _load_last_convictions() -> Dict[str, Any]:
    try:
        from internal.simivision.engine import _load_last_convictions as _load

        return dict(_load() or {})
    except Exception:
        return {}


def _persist_convictions(map_: Dict[str, Any]) -> None:
    try:
        from internal.simivision.engine import _persist_convictions as _save

        _save(map_)
    except Exception:
        pass


def _call_context(daily_pick: Optional[Dict[str, Any]]) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """Return (netuid, conviction_pct, resolves_in) from daily pick payload."""
    if not isinstance(daily_pick, dict):
        return None, None, None
    block = None
    for key in ("pick", "candidate"):
        cand = daily_pick.get(key)
        if isinstance(cand, dict) and cand.get("subnet"):
            block = cand
            break
    if block is None and isinstance(daily_pick.get("subnet"), dict):
        block = daily_pick
    netuid = None
    conv = None
    if isinstance(block, dict):
        sn = block.get("subnet") if isinstance(block.get("subnet"), dict) else block
        try:
            if sn.get("netuid") is not None:
                netuid = int(sn["netuid"])
        except (TypeError, ValueError):
            netuid = None
        conv = conviction_pct(
            block.get("final_confidence", block.get("confidence", daily_pick.get("confidence")))
        )
        if conv == 0 and daily_pick.get("final_confidence") is not None:
            conv = conviction_pct(daily_pick.get("final_confidence"))
    resolves_in = daily_pick.get("resolves_in")
    if resolves_in is not None:
        resolves_in = str(resolves_in)
    return netuid, conv if conv and conv > 0 else None, resolves_in


def shape_weighing_board(
    top: List[Dict[str, Any]],
    *,
    pool_count: int,
    daily_pick: Optional[Dict[str, Any]] = None,
    updated_at: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Filter/sort/annotate rows + meta for the Weighing Room UI."""
    call_netuid, call_conv, resolves_in = _call_context(daily_pick)
    last = _load_last_convictions()
    rows: List[Dict[str, Any]] = []
    for raw in top or []:
        if not isinstance(raw, dict):
            continue
        try:
            nu = int(raw["netuid"]) if raw.get("netuid") is not None else None
        except (TypeError, ValueError):
            nu = None
        if call_netuid is not None and nu == call_netuid:
            continue
        conv = conviction_pct(raw.get("conviction", 0))
        delta = _delta_for(nu, conv, last)
        prox = proximity_to_call(conv, call_conv)
        state = deliberation_state(prox, delta)
        reasons = raw.get("reasons") if isinstance(raw.get("reasons"), list) else []
        reason = (
            raw.get("call_line")
            or (str(reasons[0]) if reasons else None)
            or "Council still weighing this name."
        )
        why_not = (
            str(reasons[1]) if len(reasons) > 1 else "Has not crossed today's call threshold."
        )
        trigger = (
            "Would become the call when conviction clears the Daily Call bar "
            "and council aligns."
        )
        row = dict(raw)
        row.update(
            {
                "conviction": conv,
                "proximity": prox,
                "conviction_delta": delta,
                "deliberation_state": state,
                "reason": reason,
                "why_not": why_not,
                "trigger": trigger,
                "near_call_strip": (
                    _near_call_strip(str(reason), resolves_in=resolves_in)
                    if state == "NEAR-CALL"
                    else None
                ),
                "closest_to_call": False,
                "band": "near" if state == "NEAR-CALL" else "watching",
            }
        )
        rows.append(row)

    rows.sort(key=lambda r: (-int(r.get("proximity") or 0), -int(r.get("conviction") or 0)))
    rows = rows[:MAX_ROWS]
    if rows:
        rows[0]["closest_to_call"] = True

    persist_map = {str(r["netuid"]): r["conviction"] for r in rows if r.get("netuid") is not None}
    if persist_map:
        merged = dict(last)
        merged.update(persist_map)
        _persist_convictions(merged)

    excluded = 1 if call_netuid is not None else 0
    on_table = len(rows)
    quiet = max(0, int(pool_count or 0) - on_table - excluded)
    handoff = None
    if resolves_in:
        handoff = f"Next call locks in {resolves_in} · table freezes then"

    meta = {
        "call_netuid": call_netuid,
        "call_conviction": call_conv,
        "updated_ago": _human_updated_ago(updated_at),
        "on_table": on_table,
        "quiet_count": quiet,
        "quiet_label": f"{on_table} on table · {quiet} quiet",
        "handoff": handoff,
        "gap_tick_pct": call_conv,
    }
    return rows, meta
