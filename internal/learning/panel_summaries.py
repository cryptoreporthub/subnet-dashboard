"""Plain-language panel summaries from live Soul-Map / learning state."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _sentences(parts: List[str]) -> Dict[str, Any]:
    text = " ".join(p.strip() for p in parts if p and p.strip())
    return {"text": text, "sentences": [p.strip() for p in parts if p and p.strip()]}


def summarize_council() -> Dict[str, Any]:
    from internal.council.weights import _load_raw, load_weights

    weights = load_weights()
    if not weights:
        return _sentences(["Council expert weights are not loaded yet; all experts sit at default influence."])

    leader = max(weights.items(), key=lambda kv: float(kv[1] or 0))
    leader_name, leader_w = leader[0], float(leader[1])
    sorted_experts = sorted(weights.items(), key=lambda kv: float(kv[1] or 0), reverse=True)

    data = _load_raw()
    sms = data.get("soul_map_state") or {}
    decisions = (sms.get("last_selector_output") or {}).get("decisions") or []
    accum = sum(1 for d in decisions if d.get("recommended_action") == "accumulate")
    reduce = sum(1 for d in decisions if d.get("recommended_action") == "reduce")

    parts = [
        f"The Council currently weights {leader_name.replace('_', ' ').title()} highest at {leader_w:.2f}, "
        f"so that expert lane leads scoring and disposition calls.",
        "Expert influence ranks as "
        + ", ".join(f"{name} ({float(w):.2f})" for name, w in sorted_experts[:4])
        + ".",
    ]
    if decisions:
        parts.append(
            f"The latest Soul-Map rotation snapshot shows {accum} accumulate, {reduce} reduce, "
            f"and {len(decisions) - accum - reduce} hold dispositions across {len(decisions)} subnets."
        )
    else:
        parts.append("Daily selector rotation has not refreshed dispositions in this snapshot yet.")
    return _sentences(parts)


def summarize_judges() -> Dict[str, Any]:
    try:
        from internal.judges.portfolios import _load as load_portfolios
    except Exception:
        return _sentences(["Judge portfolios are unavailable; Oracle, Echo, and Pulse paper tracks cannot be read."])

    data = load_portfolios()
    parts: List[str] = []
    for name in ("oracle", "echo", "pulse"):
        block = data.get(name) or {}
        summary = block.get("summary") or {}
        win_pct = float(summary.get("win_pct", 0) or 0)
        pnl = float(summary.get("total_pnl_pct", 0) or 0)
        open_n = int(summary.get("open_positions", 0) or 0)
        parts.append(
            f"{name.title()} holds {open_n} open paper positions with {win_pct:.0f}% win rate "
            f"and {pnl:+.2f}% cumulative P&L."
        )
    if not parts:
        parts.append("Oracle, Echo, and Pulse have not recorded paper positions yet.")
    parts.append("Post-mortems fire automatically when a resolved pick was wrong, feeding the learning loop.")
    return _sentences(parts)


def summarize_learning() -> Dict[str, Any]:
    from internal.council import resolver
    from internal.council.weights import load_weights
    from internal.learning.predictions_store import load_predictions, update_stats

    weights = load_weights()
    resolved = resolver.get_resolved_predictions()
    stats = resolved.get("stats") or {}
    correct = int(stats.get("correct", 0) or 0)
    wrong = int(stats.get("wrong", 0) or 0)
    pending = int(stats.get("pending", 0) or 0)
    accuracy = float(stats.get("accuracy", 0) or 0)

    pred_data = load_predictions()
    update_stats(pred_data)
    pending = int(pred_data.get("stats", {}).get("pending", pending))

    top_expert = max(weights.items(), key=lambda kv: float(kv[1] or 0))[0] if weights else "quant"

    parts = [
        f"The learning loop shows {correct} correct and {wrong} wrong resolved predictions "
        f"({accuracy * 100:.1f}% accuracy) with {pending} still pending.",
        f"Correct calls nudge expert weights +0.02 and misses nudge −0.03; {top_expert.replace('_', ' ').title()} "
        f"currently carries the strongest learned weight at {float(weights.get(top_expert, 1.0)):.2f}.",
        "The resolver scheduler grades due picks against live prices so outcomes feed back into the next Council score.",
    ]
    if pending == 0:
        parts.append("No pending predictions are queued — hour/day pick endpoints will enqueue new rows on the next call.")
    return _sentences(parts)


def summarize_picks() -> Dict[str, Any]:
    parts: List[str] = []
    try:
        from fetchers.taomarketcap import get_all_subnets
        from internal.council.daily_pick_engine import get_or_create_today_pick
        from internal.council.hourly_pick import select_hourly_pick
        from internal.council.weights import load_weights

        subnets = get_all_subnets() or []
        ctx = {"tao_change_24h": 0.0, "weights": load_weights()}
        hour_pick = select_hourly_pick(subnets, ctx) if subnets else {}
        daily = get_or_create_today_pick(subnets, ctx)
    except Exception as exc:
        return _sentences([f"Pick engine could not load live state: {exc}"])

    if hour_pick and hour_pick.get("subnet"):
        sn = (hour_pick.get("subnet") or {}).get("name") or "unknown"
        conf = float(hour_pick.get("confidence", hour_pick.get("final_confidence", 0)) or 0)
        parts.append(
            f"Hour pick leads with {sn} at {conf * 100:.0f}% confidence using short-horizon state-vector scoring."
        )
    else:
        parts.append("No hour pick is available from the current subnet snapshot.")

    pick = daily.get("pick") if isinstance(daily, dict) else None
    action = daily.get("action", "HOLD") if isinstance(daily, dict) else "HOLD"
    if pick and isinstance(pick, dict):
        subnet = pick.get("subnet") or {}
        name = subnet.get("name") or f"SN{subnet.get('netuid')}"
        fc = float(pick.get("final_confidence", pick.get("confidence", 0)) or 0)
        audit = pick.get("audit") or {}
        approved = audit.get("approved", True)
        badge = "RedTeam APPROVED" if approved else "RedTeam HOLD — concerns flagged"
        parts.append(
            f"Daily pick is {name} ({action.upper()}) with {fc * 100:.0f}% final confidence; audit badge: {badge}."
        )
        concerns = audit.get("concerns") or []
        if concerns:
            parts.append(f"RedTeam notes: {concerns[0]}.")
    else:
        parts.append(f"Daily pick is on {action} today — confidence gate or audit blocked a live rotation pick.")

    parts.append("Top/day pick lists refresh from TaoMarketCap subnets with learned expert weights applied.")
    return _sentences(parts)


def summarize_pump_guarded() -> Optional[Dict[str, Any]]:
    try:
        from internal.analytics.pump_summary import summarize_pump

        return summarize_pump()
    except ImportError:
        return None
    except Exception:
        return None


def summarize_scenario_guarded() -> Optional[Dict[str, Any]]:
    try:
        from internal.analytics.scenario_summary import summarize_scenario

        return summarize_scenario()
    except ImportError:
        return None
    except Exception:
        return None
