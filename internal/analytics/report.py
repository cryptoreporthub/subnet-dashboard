"""Per-subnet exportable analysis report (markdown + structured sections)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from internal.analytics.backtest import evaluate_judges, run_backtest
from internal.judges.subnet_judges import score_subnet


def _find_subnet(subnets: List[Dict[str, Any]], netuid: int) -> Optional[Dict[str, Any]]:
    for sn in subnets:
        uid = sn.get("netuid", sn.get("id"))
        if uid is not None and int(uid) == int(netuid):
            return sn
    return None


def _subnet_history(netuid: int, limit: int = 12) -> List[Dict[str, Any]]:
    bt = run_backtest(limit=500)
    rows = [h for h in bt.get("history") or [] if h.get("netuid") == netuid]
    return rows[:limit]


def build_subnet_report(netuid: int) -> Dict[str, Any]:
    """Build honest-empty or populated subnet report payload."""
    try:
        from server import _get_subnets_with_source

        subnets, source = _get_subnets_with_source()
    except Exception as exc:
        return {
            "status": "error",
            "netuid": netuid,
            "error": str(exc),
            "markdown": f"# Subnet SN{netuid}\n\nRegistry unavailable — report cannot be generated.",
            "sections": {},
        }

    subnet = _find_subnet(subnets, netuid)
    if subnet is None:
        return {
            "status": "empty",
            "netuid": netuid,
            "source": source,
            "message": f"SN{netuid} not found in current registry.",
            "markdown": f"# Subnet SN{netuid}\n\nNot in registry — no live economics to report.",
            "sections": {},
        }

    name = subnet.get("name") or f"SN{netuid}"
    try:
        judges = score_subnet(netuid, subnet, use_chain=False)
    except Exception:
        judges = {}

    indicators: Dict[str, Any] = {}
    try:
        from internal.indicators.indicator_engine import IndicatorEngine

        state = IndicatorEngine().get_indicator_state()
        for row in state.get("subnets") or []:
            if int(row.get("netuid", -1)) == int(netuid):
                indicators = row
                break
    except Exception:
        pass

    history = _subnet_history(netuid)
    price = subnet.get("price")
    chg = subnet.get("price_change_24h")
    apy = subnet.get("apy")
    if apy is not None and float(apy) <= 1:
        apy = float(apy) * 100

    lines = [
        f"# {name} (SN{netuid})",
        "",
        "## Registry snapshot",
        f"- Data source: {source}",
        f"- Price: {price if price is not None else '—'}",
        f"- 24h change: {chg if chg is not None else '—'}%",
        f"- APY: {round(float(apy), 2) if apy is not None else '—'}%",
        "",
        "## Judge scores",
    ]
    for lane in ("oracle", "echo", "pulse", "consensus"):
        block = judges.get(lane) if isinstance(judges, dict) else None
        if isinstance(block, dict):
            lines.append(
                f"- **{lane.title()}**: score {block.get('score', '—')} "
                f"(confidence {block.get('confidence', '—')})"
            )
        else:
            lines.append(f"- **{lane.title()}**: —")
    lines.extend(["", "## Resolved prediction history", ""])
    if history:
        for row in history:
            lines.append(
                f"- {row.get('id', '?')}: predicted {row.get('predicted_pct')}% "
                f"→ actual {row.get('actual_pct')}% "
                f"({'hit' if row.get('council_correct') else 'miss'})"
            )
    else:
        lines.append("_No resolved backtest rows for this subnet yet._")

    if indicators:
        lines.extend(["", "## Technical indicators", f"- State: {indicators.get('signal', '—')}"])

    markdown = "\n".join(lines)
    return {
        "status": "success",
        "netuid": netuid,
        "name": name,
        "source": source,
        "markdown": markdown,
        "sections": {
            "registry": subnet,
            "judges": judges,
            "indicators": indicators or None,
            "backtest_history": history,
        },
    }
