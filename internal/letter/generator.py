"""§17.F4 — weekly letter markdown from existing stats (honest empty OK)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

DAILY_PICKS_PATH = os.environ.get("DAILY_PICKS_PATH", os.path.join("data", "daily_picks.json"))


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_daily_picks(path: Optional[str] = None) -> List[Dict[str, Any]]:
    path = path or DAILY_PICKS_PATH
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return []
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        rows = data.get("picks") or data.get("history") or []
        return [row for row in rows if isinstance(row, dict)]
    return []


def _top_pick_block(picks: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not picks:
        return {"available": False, "summary": None}
    latest = picks[-1]
    pick = latest.get("pick")
    candidate = latest.get("candidate") or {}
    subnet = None
    if isinstance(pick, dict):
        subnet = pick.get("subnet") or pick
    elif isinstance(candidate, dict):
        subnet = candidate.get("subnet") or candidate
    if not isinstance(subnet, dict):
        return {
            "available": False,
            "summary": None,
            "date": latest.get("date"),
            "action": latest.get("action"),
            "reason": latest.get("reason"),
        }
    name = subnet.get("name") or "unknown"
    netuid = subnet.get("netuid")
    action = latest.get("action")
    if isinstance(pick, dict) and pick.get("action"):
        action = action or pick.get("action")
    return {
        "available": pick is not None,
        "summary": f"SN{netuid} {name}" if netuid is not None else str(name),
        "netuid": netuid,
        "name": name,
        "action": action,
        "date": latest.get("date"),
        "reason": latest.get("reason"),
        "held": pick is None,
    }


def _scenarios_block(limit: int = 3) -> List[Dict[str, Any]]:
    try:
        from internal.council import scenario_memory

        snap = scenario_memory.get_memory_snapshot()
        scenarios = [s for s in (snap.get("scenarios") or []) if isinstance(s, dict)]
    except Exception:
        return []
    # Prefer recent resolved; fill with pending if needed.
    resolved = [s for s in scenarios if s.get("outcome")]
    pool = resolved if resolved else scenarios
    out: List[Dict[str, Any]] = []
    for s in pool[-limit:]:
        out.append(
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "regime": s.get("regime"),
                "outcome": s.get("outcome"),
                "created_at": s.get("created_at"),
            }
        )
    return out


def _win_rate_block() -> Dict[str, Any]:
    try:
        from internal.portfolio.engine import build_portfolio_status

        status = build_portfolio_status()
        summary = status.get("summary") or {}
        closed = int(summary.get("total_closed") or 0)
        if closed <= 0:
            return {"available": False, "win_pct": None, "total_closed": 0}
        return {
            "available": True,
            "win_pct": summary.get("win_pct"),
            "total_closed": closed,
            "win_count": summary.get("win_count"),
            "total_pnl_pct": summary.get("total_pnl_pct"),
            "excess_vs_hold_tao_pct": summary.get("excess_vs_hold_tao_pct"),
        }
    except Exception:
        return {"available": False, "win_pct": None, "total_closed": 0}


def _render_markdown(
    *,
    week_of: str,
    top_pick: Dict[str, Any],
    win_rate: Dict[str, Any],
    scenarios: List[Dict[str, Any]],
) -> str:
    lines = [f"# SimiVision weekly letter — week of {week_of}", ""]

    lines.append("## Top pick")
    if top_pick.get("available") and top_pick.get("summary"):
        lines.append(f"- **{top_pick['summary']}** ({top_pick.get('action') or 'long'})")
        if top_pick.get("reason"):
            lines.append(f"- {top_pick['reason']}")
    elif top_pick.get("held"):
        lines.append("- No published long this period (honest HOLD / gate).")
        if top_pick.get("reason"):
            lines.append(f"- {top_pick['reason']}")
    else:
        lines.append("- No top pick data yet.")
    lines.append("")

    lines.append("## Win rate")
    if win_rate.get("available"):
        pct = float(win_rate.get("win_pct") or 0) * 100
        lines.append(
            f"- Direction hit-rate: **{pct:.1f}%** "
            f"({win_rate.get('win_count')}/{win_rate.get('total_closed')} closed)"
        )
        if win_rate.get("excess_vs_hold_tao_pct") is not None:
            lines.append(
                f"- Paper P&L vs hold TAO: **{win_rate['excess_vs_hold_tao_pct']}%**"
            )
    else:
        lines.append("- No gradeable resolved picks yet.")
    lines.append("")

    lines.append("## Scenarios (≤3)")
    if not scenarios:
        lines.append("- No scenarios recorded yet.")
    else:
        for s in scenarios:
            label = s.get("name") or s.get("id") or "scenario"
            outcome = s.get("outcome") or "pending"
            regime = s.get("regime") or "unknown"
            lines.append(f"- {label} — {regime} — {outcome}")
    lines.append("")
    return "\n".join(lines)


def build_weekly_letter(
    *,
    daily_picks_path: Optional[str] = None,
    week_of: Optional[str] = None,
) -> Dict[str, Any]:
    week_of = week_of or _utcnow()
    picks = _load_daily_picks(daily_picks_path)
    top_pick = _top_pick_block(picks)
    win_rate = _win_rate_block()
    scenarios = _scenarios_block(3)
    empty = (
        not top_pick.get("available")
        and not top_pick.get("held")
        and not win_rate.get("available")
        and not scenarios
    )
    markdown = _render_markdown(
        week_of=week_of,
        top_pick=top_pick,
        win_rate=win_rate,
        scenarios=scenarios,
    )
    return {
        "status": "ok",
        "empty": empty,
        "week_of": week_of,
        "top_pick": top_pick,
        "win_rate": win_rate,
        "scenarios": scenarios,
        "markdown": markdown,
    }
