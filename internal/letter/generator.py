"""§17.F4 — weekly letter markdown from existing stats (honest empty OK)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

DAILY_PICKS_PATH = os.environ.get("DAILY_PICKS_PATH", os.path.join("data", "daily_picks.json"))
ALERTS_PATH = os.environ.get("ALERTS_PATH", os.path.join("data", "alerts.json"))
_SKIP_OUTCOMES = frozenset({"duplicate", "expired", "ungradeable"})


def _iso_date(val: Any) -> Optional[str]:
    if val is None:
        return None
    s = str(val)
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return None


def _yesterday_utc() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


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


def _picks_on_date(picks: List[Dict[str, Any]], date: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in picks:
        if not isinstance(row, dict):
            continue
        row_date = row.get("date") or _iso_date(row.get("timestamp_utc"))
        if row_date == date:
            out.append(row)
    return out


def _summarize_pick(row: Dict[str, Any]) -> Dict[str, Any]:
    pick = row.get("pick")
    candidate = row.get("candidate") or {}
    subnet = None
    if isinstance(pick, dict):
        subnet = pick.get("subnet") or pick
    elif isinstance(candidate, dict):
        subnet = candidate.get("subnet") or candidate
    netuid = subnet.get("netuid") if isinstance(subnet, dict) else None
    name = subnet.get("name") if isinstance(subnet, dict) else None
    action = row.get("action")
    if isinstance(pick, dict) and pick.get("action"):
        action = action or pick.get("action")
    summary = f"SN{netuid} {name}" if netuid is not None and name else (name or "pick")
    return {
        "summary": summary,
        "netuid": netuid,
        "name": name,
        "action": action,
        "reason": row.get("reason"),
        "published": pick is not None,
        "timestamp_utc": row.get("timestamp_utc"),
    }


def _resolutions_on_date(date: str) -> List[Dict[str, Any]]:
    try:
        from internal.council.grading import direction_correct
        from internal.learning.predictions_store import load_predictions

        data = load_predictions()
        items: List[Dict[str, Any]] = []
        for pred in data.get("resolved") or []:
            if not isinstance(pred, dict):
                continue
            if pred.get("outcome") in _SKIP_OUTCOMES:
                continue
            if _iso_date(pred.get("resolved_at") or pred.get("created_at")) != date:
                continue
            actual = pred.get("actual_pct")
            if actual is None:
                continue
            correct = pred.get("correct")
            if correct is None:
                try:
                    correct = direction_correct(pred, float(actual))
                except Exception:
                    correct = None
            if correct is None:
                continue
            netuid = pred.get("netuid")
            items.append(
                {
                    "id": pred.get("id"),
                    "netuid": netuid,
                    "name": pred.get("name") or (f"SN{netuid}" if netuid is not None else "—"),
                    "predicted_pct": pred.get("predicted_pct"),
                    "actual_pct": actual,
                    "outcome": "correct" if correct else "wrong",
                    "resolved_at": pred.get("resolved_at"),
                }
            )
        return items
    except Exception:
        return []


def _scenarios_on_date(date: str, limit: int = 3) -> List[Dict[str, Any]]:
    try:
        from internal.council import scenario_memory

        snap = scenario_memory.get_memory_snapshot()
        scenarios = [s for s in (snap.get("scenarios") or []) if isinstance(s, dict)]
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for s in scenarios:
        if _iso_date(s.get("created_at")) != date:
            continue
        out.append(
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "regime": s.get("regime"),
                "outcome": s.get("outcome"),
                "created_at": s.get("created_at"),
            }
        )
        if len(out) >= limit:
            break
    return out


def _alerts_on_date(date: str, limit: int = 3) -> List[Dict[str, Any]]:
    try:
        with open(ALERTS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        alerts = data.get("alerts") or []
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for row in alerts:
        if not isinstance(row, dict):
            continue
        if _iso_date(row.get("timestamp")) != date:
            continue
        out.append(
            {
                "id": row.get("id"),
                "alert_type": row.get("alert_type"),
                "severity": row.get("severity"),
                "message": row.get("message"),
                "timestamp": row.get("timestamp"),
            }
        )
        if len(out) >= limit:
            break
    return out


def _render_daily_markdown(
    *,
    date: str,
    picks: List[Dict[str, Any]],
    resolutions: List[Dict[str, Any]],
    scenarios: List[Dict[str, Any]],
    alerts: List[Dict[str, Any]],
) -> str:
    lines = [f"# SimiVision daily recap — {date}", ""]

    lines.append("## Picks")
    if not picks:
        lines.append("- No council picks recorded for this day.")
    else:
        for p in picks:
            pub = "published" if p.get("published") else "hold/candidate"
            lines.append(f"- **{p.get('summary')}** ({p.get('action') or pub})")
            if p.get("reason"):
                lines.append(f"  - {p['reason']}")
    lines.append("")

    lines.append("## Resolutions")
    if not resolutions:
        lines.append("- No gradeable resolutions on this day.")
    else:
        correct = sum(1 for r in resolutions if r.get("outcome") == "correct")
        lines.append(f"- {correct}/{len(resolutions)} direction hits")
        for r in resolutions[:5]:
            lines.append(
                f"- {r.get('name')} — pred {r.get('predicted_pct')}% → actual {r.get('actual_pct')}% ({r.get('outcome')})"
            )
    lines.append("")

    lines.append("## Scenarios")
    if not scenarios:
        lines.append("- No scenarios recorded for this day.")
    else:
        for s in scenarios:
            label = s.get("name") or s.get("id") or "scenario"
            lines.append(f"- {label} — {s.get('regime') or 'unknown'} — {s.get('outcome') or 'pending'}")
    lines.append("")

    lines.append("## Alerts")
    if not alerts:
        lines.append("- No notable alerts for this day.")
    else:
        for a in alerts:
            lines.append(f"- {a.get('message') or a.get('alert_type') or 'alert'}")
    lines.append("")
    return "\n".join(lines)


def build_daily_letter(
    *,
    date: Optional[str] = None,
    daily_picks_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Morning briefing for prior calendar day (UTC default)."""
    target = date or _yesterday_utc()
    raw_picks = _picks_on_date(_load_daily_picks(daily_picks_path), target)
    picks = [_summarize_pick(row) for row in raw_picks]
    resolutions = _resolutions_on_date(target)
    scenarios = _scenarios_on_date(target, 3)
    alerts = _alerts_on_date(target, 3)
    empty = not picks and not resolutions and not scenarios and not alerts
    stats = {
        "pick_count": len(picks),
        "resolved_count": len(resolutions),
        "correct": sum(1 for r in resolutions if r.get("outcome") == "correct"),
        "wrong": sum(1 for r in resolutions if r.get("outcome") == "wrong"),
    }
    markdown = _render_daily_markdown(
        date=target,
        picks=picks,
        resolutions=resolutions,
        scenarios=scenarios,
        alerts=alerts,
    )
    return {
        "status": "ok",
        "empty": empty,
        "date": target,
        "default_window": "yesterday_utc",
        "picks": picks,
        "resolutions": resolutions,
        "scenarios": scenarios,
        "alerts": alerts,
        "stats": stats,
        "markdown": markdown,
    }
