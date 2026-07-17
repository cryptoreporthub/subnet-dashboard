"""§21 L5 — linear cause chain for today's council pick (mindmap story path)."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SKIP = frozenset({"duplicate", "expired", "ungradeable"})


def _step(
    step_id: str,
    label: str,
    title: str,
    detail: str,
    *,
    status: str = "done",
) -> Dict[str, Any]:
    return {
        "id": step_id,
        "label": label,
        "title": title,
        "detail": detail,
        "status": status,
    }


def _pick_block(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    pick = payload.get("pick")
    if isinstance(pick, dict) and pick.get("subnet"):
        return pick
    cand = payload.get("candidate")
    if isinstance(cand, dict) and cand.get("subnet"):
        return cand
    return None


def _signal_step(pick: Dict[str, Any], subnet: Dict[str, Any]) -> Dict[str, Any]:
    signals: List[str] = []
    si = pick.get("signal_impact") or pick.get("signals")
    if isinstance(si, dict):
        impacts = si.get("impacts")
        if isinstance(impacts, list):
            for item in impacts[:4]:
                if isinstance(item, dict) and item.get("signal"):
                    signals.append(str(item["signal"]).replace("_", " "))
        active = si.get("active_signals")
        if isinstance(active, list):
            signals.extend(str(s).replace("_", " ") for s in active[:3])
    ec = pick.get("expert_contributions") or {}
    nested = ec.get("active_signals")
    if isinstance(nested, list):
        signals.extend(str(s).replace("_", " ") for s in nested[:3])

    snap = subnet if isinstance(subnet, dict) else {}
    if snap.get("yield_trap"):
        signals.append("yield trap")
    driver = snap.get("return_driver") or snap.get("dominant_driver")
    if driver:
        signals.append(str(driver).replace("_", " "))

    uniq: List[str] = []
    for s in signals:
        if s and s not in uniq:
            uniq.append(s)
        if len(uniq) >= 4:
            break

    if uniq:
        title = ", ".join(uniq[:3])
        detail = f"{len(uniq)} signal(s) fired on pick-time snapshot"
    else:
        title = "Market scan"
        detail = "Council scored subnet momentum and technicals"
    return _step("signals", "1 · Signals", title, detail)


def _judge_step(pick: Dict[str, Any]) -> Dict[str, Any]:
    ec = pick.get("expert_contributions") or {}
    ranked: List[tuple[str, float]] = []
    for name, raw in ec.items():
        if name in ("signal_contributions", "active_signals"):
            continue
        try:
            ranked.append((str(name), float(raw)))
        except (TypeError, ValueError):
            continue
    ranked.sort(key=lambda x: x[1], reverse=True)
    if ranked:
        top_name, top_val = ranked[0]
        label = top_name.replace("_", " ").title()
        others = ", ".join(n.replace("_", " ").title() for n, _ in ranked[1:3])
        detail = f"{label} led ({top_val:.2f})"
        if others:
            detail += f" · also {others}"
        return _step("judges", "2 · Council experts", f"Council blend → {label}", detail)
    return _step("judges", "2 · Council experts", "Four-expert council", "Quant · Hype · Dark horse · Technical")


def _council_step(payload: Dict[str, Any], pick: Dict[str, Any], subnet: Dict[str, Any]) -> Dict[str, Any]:
    act = str(payload.get("action") or pick.get("action") or "HOLD").upper()
    if act == "LONG":
        act = "BUY"
    name = subnet.get("name") or f"SN{subnet.get('netuid', '?')}"
    reasons = pick.get("reasons") or []
    why = reasons[0] if reasons else payload.get("reason") or ""
    detail = why or f"Audited {act} on SN{subnet.get('netuid')}"
    status = "done" if payload.get("pick") else "pending"
    return _step("council", "3 · Council pick", f"{act} {name}", str(detail)[:120], status=status)


def _outcome_step(netuid: Optional[int]) -> Dict[str, Any]:
    try:
        from internal.learning.predictions_store import load_predictions

        data = load_predictions()
        pending = data.get("predictions") or []
        resolved = data.get("resolved") or []
        for pred in pending:
            if not isinstance(pred, dict):
                continue
            if netuid is not None and pred.get("netuid") != netuid:
                continue
            stmt = pred.get("statement") or pred.get("direction") or "pending"
            pct = pred.get("predicted_pct")
            detail = f"Tracking {pred.get('horizon_type', 'hour')} horizon"
            if pct is not None:
                detail = f"Expected {float(pct):+.1f}% · {detail}"
            return _step(
                "outcome",
                "4 · Outcome",
                "Awaiting grade",
                f"{stmt} — {detail}",
                status="pending",
            )
        for pred in reversed(resolved):
            if not isinstance(pred, dict):
                continue
            if pred.get("outcome") in _SKIP:
                continue
            if netuid is not None and pred.get("netuid") != netuid:
                continue
            correct = pred.get("correct")
            if correct is None:
                continue
            verdict = "Hit" if correct else "Miss"
            actual = pred.get("actual_pct")
            detail = pred.get("statement") or verdict
            if actual is not None:
                detail = f"{verdict} · actual {float(actual):+.1f}%"
            return _step("outcome", "4 · Outcome", verdict, str(detail)[:120], status="done")
    except Exception as exc:
        logger.warning("story path outcome step failed: %s", exc)
    return _step(
        "outcome",
        "4 · Outcome",
        "Not tracked yet",
        "Prediction ledger will show grade when resolver runs",
        status="pending",
    )


def _weight_step() -> Dict[str, Any]:
    try:
        from internal.council.weights import load_weights

        weights = load_weights()
        top = sorted(weights.items(), key=lambda x: x[1], reverse=True)[:2]
        if top:
            parts = [f"{n.replace('_', ' ')} {v:.2f}" for n, v in top]
            detail = "Learned weights · " + " · ".join(parts)
        else:
            detail = "Expert weights nudge ±0.02 on each graded outcome"
        return _step("weights", "5 · Weight nudge", "Learning loop", detail, status="pending")
    except Exception:
        return _step(
            "weights",
            "5 · Weight nudge",
            "Learning loop",
            "Resolver outcomes adjust next council blend",
            status="pending",
        )


def build_story_path(daily_pick_payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build linear cause chain: Signals → Judges → Pick → Outcome → Weights."""
    payload = daily_pick_payload
    if payload is None:
        try:
            from internal.council.daily_pick_engine import get_or_create_today_pick
            from internal.subnets.feed import load_pick_subnets

            subnets = load_pick_subnets()
            payload = get_or_create_today_pick(subnets, {})
        except Exception as exc:
            logger.warning("story path daily pick load failed: %s", exc)
            payload = {}

    if not isinstance(payload, dict):
        payload = {}

    pick = _pick_block(payload)
    if not pick:
        return {
            "data_available": False,
            "reason": "no_pick",
            "netuid": None,
            "action": str(payload.get("action") or "HOLD").upper(),
            "steps": [],
        }

    subnet = pick.get("subnet") if isinstance(pick.get("subnet"), dict) else {}
    netuid = subnet.get("netuid")
    steps = [
        _signal_step(pick, subnet),
        _judge_step(pick),
        _council_step(payload, pick, subnet),
        _outcome_step(netuid),
        _weight_step(),
    ]
    return {
        "data_available": True,
        "reason": None,
        "netuid": netuid,
        "action": str(payload.get("action") or "HOLD").upper(),
        "steps": steps,
    }
